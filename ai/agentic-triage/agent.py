"""Read-only exploration agent for the AI-enhancer pass -- see
docs/adr/0035-shared-evidence-store-and-context-prompt.md and the
"AI sample-context prompt" TODO.

Unlike ai/suggest-structs' multi-mode agent, none of this agent's tools
mutate the binary: it only ever reads evidence/functions/symbols/strings
and submits a summary string. No undo boundary is needed as a result.
"""

import string
import sys
from pathlib import Path

from .core.context import build_baseline
from .core.logging import get_logger
from .hexdump import format_hexdump
from .summarize import estimate_tokens, truncate_to_tokens

_plugin_dir = Path(__file__).parent.resolve()
_PLUGIN_NAME = "agentic_triage"
logger = get_logger("agentic_triage")


def _ensure_deps_on_path():
    deps = _plugin_dir / ".deps"
    if deps.is_dir() and str(deps) not in sys.path:
        sys.path.insert(0, str(deps))


def _build_agent_llm(provider_config):
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


class _SessionState:
    def __init__(self, bv, max_tokens, max_steps=None):
        self.bv = bv
        self.max_tokens = max_tokens
        self.max_steps = max_steps
        self.step_count = 0
        self.summary = None
        self.confirmed = False


def _build_tools(state, max_strings=200, max_functions=500):
    from langchain_core.tools import tool
    from binaryninja.enums import SymbolBinding, SymbolType

    bv = state.bv
    _import_types = {
        SymbolType.ImportAddressSymbol,
        SymbolType.ImportedFunctionSymbol,
        SymbolType.ImportedDataSymbol,
        SymbolType.ExternalSymbol,
    }

    def _log_call(name, **kwargs):
        """Log every tool call to BN's log as it happens -- gives a live
        progress signal (step N/budget) while the agent runs, without
        needing to stream the underlying LLM response into the UI."""
        state.step_count += 1
        budget = f"/{state.max_steps}" if state.max_steps else ""
        args = ", ".join(f"{k}={v!r}" for k, v in kwargs.items())
        logger.info(f"agentic-triage agent: step {state.step_count}{budget}: {name}({args})")

    @tool
    def get_evidence() -> str:
        """Return everything deterministic detectors have already found
        for this sample (framework detection, etc.) -- always check this
        before spending tool calls investigating something a detector
        already reported."""
        _log_call("get_evidence")
        baseline = build_baseline(bv)
        return baseline or "(no deterministic evidence recorded yet)"

    @tool
    def list_functions(prefix: str = None) -> str:
        """List function names (and start addresses), optionally filtered
        by a name `prefix`. Truncated to the first several hundred matches."""
        _log_call("list_functions", prefix=prefix)
        names = [(f.name, f.start) for f in bv.functions]
        if prefix:
            names = [(n, a) for n, a in names if n.startswith(prefix)]
        names = names[:max_functions]
        return "\n".join(f"{n} @ {a:#x}" for n, a in names) or "(none)"

    @tool
    def get_imports() -> str:
        """List imported symbol names."""
        _log_call("get_imports")
        names = sorted({s.name for s in bv.get_symbols() if s.type in _import_types})
        return "\n".join(names) or "(none)"

    @tool
    def get_exports() -> str:
        """List exported (globally visible) symbol names."""
        _log_call("get_exports")
        names = sorted(
            {s.name for s in bv.get_symbols() if s.type not in _import_types and s.binding == SymbolBinding.GlobalBinding}
        )
        return "\n".join(names) or "(none)"

    @tool
    def search_strings(substring: str) -> str:
        """Search for strings containing `substring` (case-insensitive).
        Truncated to the first couple hundred matches."""
        _log_call("search_strings", substring=substring)
        needle = substring.lower()
        matches = [s.value for s in bv.get_strings() if needle in s.value.lower()]
        return "\n".join(matches[:max_strings]) or "(none)"

    @tool
    def get_xrefs_to(address: int) -> str:
        """Get code and data cross-references TO `address` -- what calls
        or references it. Truncated to the first couple hundred of each."""
        _log_call("get_xrefs_to", address=hex(address))
        code_refs = [
            f"{r.function.name} @ {r.address:#x}" for r in bv.get_code_refs(address)
        ][:max_strings]
        data_refs = [f"{a:#x}" for a in bv.get_data_refs(address)][:max_strings]
        return (
            "code_refs:\n" + ("\n".join(code_refs) or "(none)")
            + "\ndata_refs:\n" + ("\n".join(data_refs) or "(none)")
        )

    @tool
    def get_xrefs_from(address: int) -> str:
        """Get code and data cross-references FROM `address` -- what it
        calls or references. Truncated to the first couple hundred of
        each."""
        _log_call("get_xrefs_from", address=hex(address))
        code_refs = [f"{a:#x}" for a in bv.get_code_refs_from(address)][:max_strings]
        data_refs = [f"{a:#x}" for a in bv.get_data_refs_from(address)][:max_strings]
        return (
            "code_refs:\n" + ("\n".join(code_refs) or "(none)")
            + "\ndata_refs:\n" + ("\n".join(data_refs) or "(none)")
        )

    @tool
    def get_function_context(address: int) -> str:
        """Return the HLIL disassembly of the function containing
        `address`, for a closer look at something interesting found via
        the other tools (e.g. the entry point, or a suspicious import's
        caller)."""
        _log_call("get_function_context", address=hex(address))
        funcs = bv.get_functions_containing(address)
        if not funcs:
            return f"error: no function contains address {address:#x}"
        func = funcs[0]
        lines = []
        if func.hlil:
            for block in func.hlil:
                if block is None:
                    continue
                for instr in block:
                    lines.append(f"  {instr.address:#x}: {instr}")
        return f"function: {func.name} ({func.start:#x})\n" + ("\n".join(lines) or "(no HLIL available)")

    @tool
    def read_data(address: int, size: int) -> str:
        """Read raw bytes at `address` and return a hex+ASCII dump, for
        inspecting a region that isn't a string or a function (e.g. a
        header, a constant table, packed/encoded data). `size` is capped
        at 4096 bytes -- request a narrower range if you need more detail
        on a specific part of a larger region."""
        _log_call("read_data", address=hex(address), size=size)
        size = min(size, 4096)
        data = bv.read(address, size)
        if not data:
            return f"error: could not read {size} byte(s) at {address:#x}"
        return format_hexdump(data, base_addr=address)

    @tool
    def submit_summary(text: str) -> str:
        """Submit your final triage summary. Required exactly once, as
        your last action -- a session that ends without calling this is
        treated as a failure. Rejected if longer than the configured word
        budget; shorten and resubmit if so."""
        _log_call("submit_summary")
        tokens = estimate_tokens(text)
        if tokens > state.max_tokens:
            return (
                f"error: summary is ~{tokens} words, over the {state.max_tokens}-word budget -- "
                "shorten it and call submit_summary again"
            )
        state.summary = text
        state.confirmed = True
        return "summary submitted"

    return [
        get_evidence,
        list_functions,
        get_imports,
        get_exports,
        search_strings,
        get_xrefs_to,
        get_xrefs_from,
        get_function_context,
        read_data,
        submit_summary,
    ]


def _run_fallback_invoke(llm, system_prompt, messages_so_far, max_tokens, provider_config, debug):
    """When the tool-calling session fails (step budget exhausted, error,
    or it ended without calling submit_summary), force one last plain
    invoke -- no tools offered -- over everything gathered so far
    (thinking, tool calls, tool results), so the user still gets a
    best-effort summary instead of nothing. `llm` is the raw chat model,
    not the tool-bound one create_deep_agent uses internally (langgraph
    binds tools to a *copy*, per suggest-structs/agent.py's note), so this
    call genuinely cannot make another tool call.

    Returns the summary text, or None if the fallback invoke itself
    failed too.
    """
    from langchain_core.messages import HumanMessage, SystemMessage

    closing_instruction = HumanMessage(content=(
        "Your tool-calling session ended without submitting a summary "
        "(step budget exhausted or an error occurred). Based only on "
        "everything above, write your best summary now as plain text -- "
        "frameworks/libraries used and the functions relevant to each, "
        "no verdicts or judgments about what the binary is, does, or is "
        "for -- follow the same formatting and content rules, at most "
        f"{max_tokens} words. Respond with the summary text only -- no "
        "tool calls, no explanation of why the session ended."
    ))
    non_system = [m for m in messages_so_far if not isinstance(m, SystemMessage)]
    messages = [SystemMessage(content=system_prompt)] + non_system + [closing_instruction]

    if debug:
        from .core import llm_debug

        llm_debug.log_request(_PLUGIN_NAME, provider_config, "\n".join(str(m) for m in messages))

    try:
        response = llm.invoke(messages)
    except Exception as e:
        logger.warning(f"agentic-triage agent: fallback invoke also failed: {e}")
        return None

    text = getattr(response, "content", None)
    if not text:
        return None
    return truncate_to_tokens(text, max_tokens)


def run_agent_session(bv, *, provider_config, max_tokens, max_steps, debug=False):
    """Run one read-only triage session. Returns (text, error).

    If the tool-calling loop fails (step budget exhausted, an exception,
    or it never calls submit_summary), a single non-tool-call fallback
    invoke is forced over the partial transcript instead of giving up
    entirely -- see _run_fallback_invoke. `error` is only set (text is
    None) if that fallback invoke also fails; a used fallback still
    returns (text, None), with a warning logged to BN's log."""
    from .core.prompts import load_prompt

    _ensure_deps_on_path()
    from deepagents import create_deep_agent
    from langgraph.errors import GraphRecursionError

    state = _SessionState(bv, max_tokens, max_steps=max_steps)
    tools = _build_tools(state)
    llm = _build_agent_llm(provider_config)

    system_prompt = string.Template(load_prompt(_plugin_dir, "agent_system.txt")).safe_substitute(
        max_tokens=max_tokens, max_steps=max_steps
    )
    baseline = build_baseline(bv) or "(no deterministic evidence recorded yet)"
    task = string.Template(load_prompt(_plugin_dir, "agent_task.txt")).safe_substitute(baseline=baseline)

    agent = create_deep_agent(model=llm, tools=tools, system_prompt=system_prompt)

    invoke_config = {"recursion_limit": max_steps * 2}
    if debug:
        from .core import llm_debug

        cb = llm_debug.make_callback(_PLUGIN_NAME, provider_config)
        if cb is not None:
            invoke_config["callbacks"] = [cb]

    logger.info(f"agentic-triage agent: starting session (step budget {max_steps}, word budget {max_tokens})")
    initial_messages = [{"role": "user", "content": task}]
    messages_so_far = initial_messages
    error = None
    try:
        # stream (not invoke) so the transcript-so-far (thinking, tool
        # calls, tool results) is captured incrementally -- if the loop
        # is cut short (recursion limit or another exception), whatever
        # was yielded before that is still available for the fallback
        # invoke below, instead of being lost with the exception.
        for chunk in agent.stream({"messages": initial_messages}, config=invoke_config, stream_mode="values"):
            if "messages" in chunk:
                messages_so_far = chunk["messages"]
    except GraphRecursionError:
        error = f"agent exceeded step budget ({max_steps}) without calling submit_summary"
    except Exception as e:
        error = str(e)

    if error is None and not state.confirmed:
        error = "agent session ended without calling submit_summary"

    if error is not None:
        logger.warning(f"agentic-triage agent: session failed after {state.step_count} step(s): {error}")
        fallback_text = _run_fallback_invoke(
            llm, system_prompt, messages_so_far, max_tokens, provider_config, debug
        )
        if fallback_text is not None:
            logger.warning(
                "agentic-triage agent: session failed, used single-shot fallback summary "
                f"over the partial transcript ({error})"
            )
            return fallback_text, None
        return None, error

    logger.info(f"agentic-triage agent: session completed in {state.step_count} step(s)")
    return state.summary, None
