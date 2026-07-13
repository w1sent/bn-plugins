from dataclasses import dataclass, field
from typing import Optional
import json
import re
import string
import sys
import threading
from pathlib import Path

from .core.ai_config import load_ai_config, resolve_provider
from .core.config_file import load_or_create_json_config
from .core.prompts import load_prompt
from .core.retry import retry_with_backoff
from .core.logging import get_logger
from .core.exceptions import AIConfigError, AITimeoutError

from . import ordering as ordering_mod
from .ordering import OrderingError

_plugin_dir = Path(__file__).resolve().parent
logger = get_logger("auto_rename")

_DEFAULT_PLUGIN_CONFIG_PATH = Path.home() / ".binaryninja" / "auto-rename.json"
_DEFAULT_PLUGIN_CONFIG = {
    "custom_prompt": None,
    "temperature": 0.1,
    "backoff_steps": [1, 2, 4, 8],
}


def _ensure_deps_on_path():
    """Re-assert .deps/ on sys.path from the calling thread.

    __init__.py already does this at plugin-load time, but langchain_ollama
    etc. are only imported lazily inside a background rename thread -- make
    that import site self-sufficient instead of depending on state set up
    on a different thread at an earlier time.
    """
    deps = _plugin_dir / ".deps"
    if deps.is_dir() and str(deps) not in sys.path:
        sys.path.insert(0, str(deps))

_VALID_NAME_RE = re.compile(r"^[a-zA-Z_][a-zA-Z_0-9:]*(::[a-zA-Z_][a-zA-Z_0-9:]*)*$")

_DEFAULT_CONCURRENCY_MODE = "sequential"
_DEFAULT_CONCURRENCY_WORKERS = 3


@dataclass
class RenameOptions:
    provider: Optional[str] = None
    mode: Optional[str] = None
    temperature: Optional[float] = None
    custom_prompt: Optional[str] = None
    ordering: Optional[str] = None
    concurrency: Optional[str] = None
    workers: Optional[int] = None


@dataclass
class RenameResult:
    address: int
    old_name: str
    new_name: Optional[str] = None
    reasoning: Optional[str] = None
    error: Optional[str] = None


class _AsyncResult:
    def __init__(self, bv, funcs, target, title, on_complete=None):
        from binaryninja import BackgroundTask

        self._results = []
        self._done = threading.Event()
        self._task = BackgroundTask(title, can_cancel=True)
        self._cancel = False
        self._on_complete = on_complete

        def _run():
            try:
                self._results = target(self._set_progress)
                if self._on_complete:
                    self._on_complete(self._results)
            finally:
                self._done.set()
                self._task.finish()

        thread = threading.Thread(target=_run, daemon=True)
        thread.start()

    def _set_progress(self, text):
        self._task.progress = text

    def done(self):
        return self._done.is_set()

    def result(self, timeout=None):
        self._done.wait(timeout=timeout)
        if not self._done.is_set():
            raise TimeoutError("operation did not finish in time")
        return self._results

    def cancel(self):
        self._cancel = True
        self._task.cancel()


def _build_context(bv, func):
    hlil_lines = []
    if func.hlil:
        for block in func.hlil:
            if block is None:
                continue
            for instr in block:
                hlil_lines.append(f"  {instr.address:#x}: {instr}")
    disassembly = "\n".join(hlil_lines) if hlil_lines else "(no HLIL available)"

    callers = []
    for ref in func.caller_sites:
        caller = ref.function
        if caller is None:
            continue
        ctx_lines = []
        if caller.hlil:
            for block in caller.hlil:
                if block is None:
                    continue
                for instr in block:
                    if instr.address == ref.address:
                        ctx_lines.append(f"  >>> {instr.address:#x}: {instr}")
                    elif abs(instr.address - ref.address) < 0x20:
                        ctx_lines.append(f"  {instr.address:#x}: {instr}")
        ctx = "\n".join(ctx_lines[-10:]) if ctx_lines else ""
        callers.append({"name": caller.name, "address": ref.address, "context": ctx})

    callees = [c.name for c in func.callees]

    string_refs = []
    if func.hlil:
        for block in func.hlil:
            if block is None:
                continue
            for instr in block:
                const = getattr(instr, "constant", None)
                if isinstance(const, int):
                    s = bv.get_string_at(const)
                    if s:
                        string_refs.append(f"  {const:#x}: {s.value}")

    data_refs = []
    if func.hlil:
        for block in func.hlil:
            if block is None:
                continue
            for instr in block:
                const = getattr(instr, "constant", None)
                if isinstance(const, int):
                    for ref_addr in bv.get_data_refs(const):
                        data = bv.read(ref_addr, 16)
                        if data:
                            hex_preview = " ".join(f"{b:02x}" for b in data)
                            data_refs.append(f"  {ref_addr:#x}: {hex_preview}")

    return {
        "function_name": func.name,
        "address": f"{func.start:#x}",
        "callers": "\n".join(
            f"  {c['name']} at {c['address']:#x}:\n{c['context']}"
            for c in callers
        )
        or "(none)",
        "callees": "\n".join(f"  {c}" for c in callees) or "(none)",
        "string_refs": "\n".join(string_refs) or "(none)",
        "data_refs": "\n".join(data_refs) or "(none)",
        "disassembly": disassembly,
    }


def _is_auto_named(func):
    name = func.name
    return (
        not func.is_import
        and not func.is_thunk
        and (
            name.startswith("sub_")
            or name.startswith("loc_")
            or name.startswith("unk_")
            or name.startswith("dword_")
            or name.startswith("byte_")
            or name.startswith("word_")
        )
    )


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


def _resolve_scheduling(bv, options):
    """Resolve (ordering, concurrency_mode, workers), options taking precedence
    over BN settings, which supply the default when the option is unset."""
    from binaryninja import Settings

    settings = Settings()
    ordering = (options.ordering if options else None) or settings.get_string(
        "auto_rename.ordering", resource=bv
    )
    concurrency = (options.concurrency if options else None) or settings.get_string(
        "auto_rename.concurrency_mode", resource=bv
    )
    workers = (options.workers if options else None) or settings.get_integer(
        "auto_rename.concurrency_workers", resource=bv
    )
    return ordering or "default", concurrency or _DEFAULT_CONCURRENCY_MODE, workers or _DEFAULT_CONCURRENCY_WORKERS


def _resolve_plugin_config(bv, options):
    """Load the complex per-plugin config (auto-rename.json by default),
    creating it with defaults on first use (see ADR-0017). `options`
    fields, when set, take precedence over the file."""
    from binaryninja import Settings

    settings = Settings()
    config_path = settings.get_string("auto_rename.config_path", resource=bv) or str(
        _DEFAULT_PLUGIN_CONFIG_PATH
    )
    try:
        file_config = load_or_create_json_config(config_path, _DEFAULT_PLUGIN_CONFIG)
    except (OSError, json.JSONDecodeError) as e:
        logger.warning(f"failed to load {config_path}, using defaults: {e}")
        file_config = dict(_DEFAULT_PLUGIN_CONFIG)

    custom_prompt = (options.custom_prompt if options else None) or file_config.get(
        "custom_prompt"
    )
    temperature = (
        options.temperature
        if options and options.temperature is not None
        else file_config.get("temperature")
    )
    backoff_steps = file_config.get("backoff_steps") or _DEFAULT_PLUGIN_CONFIG["backoff_steps"]
    return custom_prompt, temperature, backoff_steps


def _apply_temperature(provider_config, temperature):
    if temperature is None or provider_config.get("parameters", {}).get("temperature") is not None:
        return provider_config
    provider_config = dict(provider_config)
    provider_config["parameters"] = dict(provider_config.get("parameters", {}))
    provider_config["parameters"]["temperature"] = temperature
    return provider_config


def _resolve_roots(bv, ordering):
    if ordering == "top-down":
        entry = bv.entry_function
        if entry is not None:
            return [entry]
        return ordering_mod.zero_caller_roots(list(bv.functions))
    if ordering == "export-down":
        from binaryninja.enums import SymbolBinding

        return [
            f
            for f in bv.functions
            if f.symbol is not None and f.symbol.binding == SymbolBinding.GlobalBinding
        ]
    return None


def _rename_one(bv, func, prompt_template, llm, options):
    context = _build_context(bv, func)
    # $-style substitution, not str.format(): the template's example JSON
    # output ({"name": ..., "reasoning": ...}) contains literal braces that
    # str.format() would misparse as format fields.
    prompt = string.Template(prompt_template).safe_substitute(context)

    try:
        response = llm.invoke(prompt)
        content = response.content.strip()
        if content.startswith("```"):
            content = content.split("\n", 1)[-1]
            content = content.rsplit("\n```", 1)[0]
        parsed = json.loads(content)
        name = parsed.get("name", "").strip()
        reasoning = parsed.get("reasoning", "")

        if not _VALID_NAME_RE.match(name):
            return RenameResult(
                address=func.start,
                old_name=func.name,
                error=f"LLM returned invalid name: {name}",
            )

        old_name = func.name
        func.name = name
        return RenameResult(
            address=func.start,
            old_name=old_name,
            new_name=name,
            reasoning=reasoning,
        )
    except Exception as e:
        return RenameResult(
            address=func.start,
            old_name=func.name,
            error=str(e),
        )


def rename_function(
    bv, func, *, provider=None, mode=None, options=None, async_run=False, on_complete=None
):
    """Rename a single function.

    Returns RenameResult when sync, _AsyncResult when async_run=True.
    """
    custom_prompt, temperature, backoff_steps = _resolve_plugin_config(bv, options)
    ai_config = load_ai_config()
    provider_config = _apply_temperature(resolve_provider(ai_config, provider), temperature)
    llm = _build_llm(provider_config)
    prompt_template = custom_prompt or load_prompt(_plugin_dir, "rename.txt")

    def _warn(attempt, exc):
        logger.warning(
            f"rename attempt {attempt} failed for {func.name} at {func.start:#x}: {exc}"
        )

    def _fail(exc):
        logger.error(
            f"rename failed for {func.name} at {func.start:#x}: {exc}"
        )

    def _run(set_progress=None):
        if set_progress:
            set_progress(f"Renaming {func.name}...")
        return retry_with_backoff(
            _rename_one,
            args=(bv, func, prompt_template, llm, options),
            backoff_steps=backoff_steps,
            on_warning=_warn,
            on_failure=_fail,
        )

    if async_run:
        return _AsyncResult(bv, [func], _run, f"Renaming {func.name}", on_complete=on_complete)

    return _run()


def rename_functions(
    bv,
    funcs,
    *,
    provider=None,
    mode=None,
    options=None,
    anchor=None,
    restrict_to=None,
    progress=None,
    cancel=None,
    async_run=False,
    on_complete=None,
):
    """Rename multiple functions in batch.

    `anchor` is required when `options.ordering` (or the
    `auto_rename.ordering` setting) is one of the local-* strategies; see
    `ordering.NEEDS_ANCHOR`. `restrict_to`, if given, confines local-*
    graph traversal to that set of functions (e.g. a UI selection).
    Raises `ordering.OrderingError` if a required input is missing.
    """
    funcs = list(funcs)

    # Resolved and validated synchronously (not inside `_run`) so a missing
    # anchor/roots raises immediately for the caller, even when async_run=True
    # -- an exception raised inside the background thread would otherwise be
    # swallowed by _AsyncResult instead of surfacing.
    order, concurrency, workers = _resolve_scheduling(bv, options)
    roots = _resolve_roots(bv, order) if order in ordering_mod.NEEDS_ROOTS else None
    ordered_funcs = ordering_mod.order_functions(
        funcs, order, anchor=anchor, roots=roots, restrict_to=restrict_to
    )

    if (
        concurrency == "fixed-pool"
        and workers > 1
        and order in ordering_mod.PROPAGATION_DEPENDENT
    ):
        logger.warning(
            f"ordering '{order}' relies on completion order for its context-propagation "
            f"benefit; 'fixed-pool' concurrency with {workers} workers only guarantees "
            f"submission order, so that benefit may be degraded"
        )

    total = len(ordered_funcs)

    def _run(set_progress=None):
        custom_prompt, temperature, backoff_steps = _resolve_plugin_config(bv, options)
        ai_config = load_ai_config()
        provider_config = _apply_temperature(resolve_provider(ai_config, provider), temperature)
        llm = _build_llm(provider_config)
        prompt_template = custom_prompt or load_prompt(_plugin_dir, "rename.txt")

        def _report(done, result=None):
            if progress:
                progress(done, total)
            if set_progress:
                label = f"Renaming functions ({done}/{total})"
                if result is not None and result.new_name:
                    label += f": {result.old_name} -> {result.new_name}"
                set_progress(label)

        if concurrency == "fixed-pool":
            import concurrent.futures

            results = []
            with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
                future_map = {
                    pool.submit(
                        retry_with_backoff,
                        _rename_one,
                        args=(bv, f, prompt_template, llm, options),
                        backoff_steps=backoff_steps,
                    ): f
                    for f in ordered_funcs
                }
                for i, future in enumerate(concurrent.futures.as_completed(future_map)):
                    if cancel and cancel():
                        break
                    func = future_map[future]
                    try:
                        result = future.result()
                    except Exception as e:
                        result = RenameResult(address=func.start, old_name=func.name, error=str(e))
                    results.append(result)
                    _report(i + 1, result)
            return results

        results = []
        for i, func in enumerate(ordered_funcs):
            if cancel and cancel():
                break
            result = rename_function(bv, func, provider=provider, options=options)
            results.append(result)
            _report(i + 1, result)
        return results

    if async_run:
        return _AsyncResult(bv, funcs, _run, f"Renaming {total} functions", on_complete=on_complete)
    return _run()


def rename_all(
    bv,
    *,
    provider=None,
    mode=None,
    options=None,
    anchor=None,
    restrict_to=None,
    progress=None,
    cancel=None,
    async_run=False,
    on_complete=None,
):
    funcs = [f for f in bv.functions if _is_auto_named(f)]
    return rename_functions(
        bv,
        funcs,
        provider=provider,
        options=options,
        anchor=anchor,
        restrict_to=restrict_to,
        progress=progress,
        cancel=cancel,
        async_run=async_run,
        on_complete=on_complete,
    )


def rename_filtered(
    bv,
    pattern,
    *,
    provider=None,
    mode=None,
    options=None,
    anchor=None,
    restrict_to=None,
    progress=None,
    cancel=None,
    async_run=False,
    on_complete=None,
):
    import re
    compiled = re.compile(pattern)
    funcs = [f for f in bv.functions if _is_auto_named(f) and compiled.match(f.name)]
    return rename_functions(
        bv,
        funcs,
        provider=provider,
        options=options,
        anchor=anchor,
        restrict_to=restrict_to,
        progress=progress,
        cancel=cancel,
        async_run=async_run,
        on_complete=on_complete,
    )


def help():
    print("""auto-rename API
---------------
rename_function(bv, func, *, provider=None, mode=None, options=None) -> RenameResult
    Rename a single function based on its disassembly and context.

rename_functions(bv, funcs, *, provider=None, mode=None, options=None, anchor=None,
                  restrict_to=None, progress=None, cancel=None) -> list[RenameResult]
    Rename multiple functions in batch, ordered/scheduled per `options`.

rename_all(bv, *, provider=None, mode=None, options=None, anchor=None, restrict_to=None,
           progress=None, cancel=None) -> list[RenameResult]
    Rename all auto-named functions in the binary.

rename_filtered(bv, pattern, *, provider=None, mode=None, options=None, anchor=None,
                 restrict_to=None, progress=None, cancel=None) -> list[RenameResult]
    Rename functions matching a regex pattern.

Scheduling:
    `options.ordering` picks which function is renamed next (see
    `ordering.ORDERINGS`): default, leaves-first, top-down, local-breadth,
    local-bottom-up, local-up, export-down, info-gain. `local-*` orderings
    require `anchor` (raises `ordering.OrderingError` if missing).
    `restrict_to`, if given, confines local-* traversal to that set of
    functions (e.g. a UI selection); unreachable members sort last.

    `options.concurrency` picks how many run at once: "sequential" or
    "fixed-pool" (with `options.workers` workers). Ordering under
    fixed-pool is best-effort (submission order only, not completion
    order) -- a warning is logged when a propagation-dependent ordering
    (leaves-first, local-bottom-up, info-gain) is combined with
    fixed-pool and workers > 1.

    Both default from the `auto_rename.ordering` / `auto_rename.concurrency_mode`
    / `auto_rename.concurrency_workers` BN settings when unset on `options`.

Types:
    RenameResult(address: int, old_name: str, new_name: str | None, reasoning: str | None, error: str | None)
    RenameOptions(provider: str | None, mode: str | None, temperature: float | None,
                  custom_prompt: str | None, ordering: str | None, concurrency: str | None,
                  workers: int | None)
""")