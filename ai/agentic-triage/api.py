import string
import sys
import threading
from pathlib import Path

from .core.ai_config import load_ai_config, resolve_provider
from .core.context import build_baseline, record_enhancer_output
from .core.logging import get_logger
from .core.prompts import load_prompt
from .core import llm_debug
from .summarize import truncate_to_tokens

_plugin_dir = Path(__file__).parent.resolve()
logger = get_logger("agentic_triage")
_PLUGIN_NAME = "agentic_triage"

_DEFAULT_MAX_SUMMARY_TOKENS = 400
_DEFAULT_AGENT_MAX_STEPS = 80


def _ensure_deps_on_path():
    deps = _plugin_dir / ".deps"
    if deps.is_dir() and str(deps) not in sys.path:
        sys.path.insert(0, str(deps))


class _AsyncResult:
    """Mirrors ai/auto-rename's/suggest-structs' _AsyncResult -- runs
    `target` on a BN BackgroundTask-backed thread so the GUI stays
    responsive during the LLM call (ADR-0006)."""

    def __init__(self, bv, target, title, on_complete=None):
        from binaryninja import BackgroundTask

        self._result = None
        self._done = threading.Event()
        self._task = BackgroundTask(title, can_cancel=False)
        self._on_complete = on_complete

        def _run():
            try:
                self._result = target()
                if self._on_complete:
                    self._on_complete(self._result)
            finally:
                self._done.set()
                self._task.finish()

        thread = threading.Thread(target=_run, daemon=True)
        thread.start()

    def done(self):
        return self._done.is_set()

    def result(self, timeout=None):
        self._done.wait(timeout=timeout)
        if not self._done.is_set():
            raise TimeoutError("operation did not finish in time")
        return self._result


def _debug_logging_enabled(bv):
    return llm_debug.is_enabled("agentic_triage.debug_logging", bv)


def _resolve_settings(bv, max_tokens=None, agent_max_steps=None):
    from binaryninja import Settings

    settings = Settings()
    resolved_tokens = max_tokens if max_tokens is not None else settings.get_integer(
        "agentic_triage.max_summary_tokens", resource=bv
    )
    resolved_steps = agent_max_steps if agent_max_steps is not None else settings.get_integer(
        "agentic_triage.agent_max_steps", resource=bv
    )
    return resolved_tokens or _DEFAULT_MAX_SUMMARY_TOKENS, resolved_steps or _DEFAULT_AGENT_MAX_STEPS


def _build_llm(provider_config):
    _ensure_deps_on_path()
    provider_type = provider_config.get("type", "").lower()
    params = provider_config.get("parameters", {})

    if provider_type == "ollama":
        from langchain_ollama import ChatOllama

        return ChatOllama(
            model=provider_config.get("model", "llama3.1:8b"),
            base_url=provider_config.get("endpoint", "http://localhost:11434"),
            temperature=params.get("temperature", 0.1),
            num_predict=params.get("max_tokens", 4096),
        )

    if provider_type == "anthropic":
        from langchain_anthropic import ChatAnthropic

        return ChatAnthropic(
            model=provider_config.get("model", "claude-3-5-sonnet-latest"),
            api_key=provider_config.get("api_key"),
            temperature=params.get("temperature", 0.1),
            max_tokens=params.get("max_tokens", 4096),
        )

    if provider_type == "google":
        from langchain_google_genai import ChatGoogleGenerativeAI

        return ChatGoogleGenerativeAI(
            model=provider_config.get("model", "gemini-2.0-flash"),
            api_key=provider_config.get("api_key"),
            temperature=params.get("temperature", 0.1),
        )

    from langchain_openai import ChatOpenAI

    kwargs = {
        "model": provider_config.get("model", "gpt-4o"),
        "temperature": params.get("temperature", 0.1),
        "max_tokens": params.get("max_tokens", 4096),
    }
    api_key = provider_config.get("api_key")
    if api_key:
        kwargs["api_key"] = api_key
    endpoint = provider_config.get("endpoint")
    if endpoint:
        kwargs["base_url"] = endpoint
    return ChatOpenAI(**kwargs)


def _gather_quick_facts(bv, max_strings=20):
    """Cheap, deterministic structural facts for the quick (non-agentic)
    path -- no tool loop, so everything the prompt needs must be gathered
    up front."""
    from binaryninja.enums import SymbolBinding, SymbolType

    import_types = {
        SymbolType.ImportAddressSymbol,
        SymbolType.ImportedFunctionSymbol,
        SymbolType.ImportedDataSymbol,
        SymbolType.ExternalSymbol,
    }
    all_symbols = list(bv.get_symbols())

    entry_funcs = [f.name for f in bv.functions if f.start == bv.entry_point]
    imports = sorted({s.name for s in all_symbols if s.type in import_types})
    exports = sorted(
        {s.name for s in all_symbols if s.type not in import_types and s.binding == SymbolBinding.GlobalBinding}
    )
    strings = [s.value for s in bv.get_strings()][:max_strings]

    return (
        f"entry point: {entry_funcs[0] if entry_funcs else hex(bv.entry_point)}\n"
        f"function count: {len(list(bv.functions))}\n"
        f"imports ({len(imports)} total, showing up to 40): {', '.join(imports[:40]) or '(none)'}\n"
        f"exports ({len(exports)} total, showing up to 40): {', '.join(exports[:40]) or '(none)'}\n"
        f"sample strings: {' | '.join(strings) or '(none)'}"
    )


def run_quick_enhance(bv, *, provider=None, max_tokens=None, async_run=False, on_complete=None):
    """Single-shot, non-agentic enhancement: one LLM call over curated
    deterministic data (evidence-store baseline + cheap structural facts),
    no tool loop. Cheaper and faster than run_agent_enhance, at the cost of
    not being able to investigate anything not already gathered here.

    Returns the summary text (also recorded via
    core.context.record_enhancer_output). `on_complete(text)` is called
    with the same value when `async_run=True`.
    """
    resolved_tokens, _steps = _resolve_settings(bv, max_tokens=max_tokens)
    debug = _debug_logging_enabled(bv)

    def _run():
        ai_config = load_ai_config()
        provider_config = resolve_provider(ai_config, provider)
        llm = _build_llm(provider_config)

        baseline = build_baseline(bv) or "(no deterministic evidence recorded yet)"
        facts = _gather_quick_facts(bv)
        prompt = string.Template(load_prompt(_plugin_dir, "quick_prompt.txt")).safe_substitute(
            baseline=baseline, facts=facts, max_tokens=resolved_tokens
        )

        if debug:
            llm_debug.log_request(_PLUGIN_NAME, provider_config, prompt)
        response = llm.invoke(prompt)
        text = truncate_to_tokens(response.content, resolved_tokens)
        record_enhancer_output(bv, text)
        return text

    if async_run:
        return _AsyncResult(bv, _run, "Agentic Triage: quick enhance", on_complete=on_complete)
    return _run()


def run_agent_enhance(bv, *, provider=None, max_tokens=None, agent_max_steps=None, async_run=False, on_complete=None):
    """Full enhancement: a read-only exploration agent investigates the
    binary (see agent.py) and produces the summary. More thorough than
    run_quick_enhance, at the cost of a multi-step agent session.

    Returns (text, error). If the agent's tool-calling session fails, a
    single-shot fallback forces a summary from whatever was gathered
    before the failure (see agent.py's run_agent_session) -- `error` is
    only set (text is None) if that fallback fails too, so most failures
    still produce usable text with a warning logged to BN's log instead
    of an outright error. `on_complete((text, error))` is called with the
    same tuple when `async_run=True`.
    """
    from . import agent as agent_mod

    resolved_tokens, resolved_steps = _resolve_settings(
        bv, max_tokens=max_tokens, agent_max_steps=agent_max_steps
    )
    debug = _debug_logging_enabled(bv)

    def _run():
        ai_config = load_ai_config()
        provider_config = resolve_provider(ai_config, provider)
        text, error = agent_mod.run_agent_session(
            bv, provider_config=provider_config, max_tokens=resolved_tokens, max_steps=resolved_steps,
            debug=debug,
        )
        if error is None:
            text = truncate_to_tokens(text, resolved_tokens)
            record_enhancer_output(bv, text)
        return text, error

    if async_run:
        return _AsyncResult(bv, _run, "Agentic Triage: running analysis", on_complete=on_complete)
    return _run()


def help():
    print("""agentic-triage API
-------------------
run_quick_enhance(bv, *, provider=None, max_tokens=None) -> str
    Single LLM call over curated evidence-store data + cheap structural facts
    (entry point, imports/exports, sample strings). No tool loop.

run_agent_enhance(bv, *, provider=None, max_tokens=None, agent_max_steps=None) -> (str | None, str | None)
    Read-only exploration agent (see agent.py) investigates the binary and
    produces the summary. Returns (text, error).

Both record their result via core.context.record_enhancer_output(bv, text)
on success -- see docs/adr/0035-shared-evidence-store-and-context-prompt.md.
Both are truncated to the configured `agentic_triage.max_summary_tokens`
(approximate, word-count based -- see summarize.py).
""")
