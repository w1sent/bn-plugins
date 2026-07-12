from dataclasses import dataclass, field
from typing import Optional
import json
import re
import threading
from pathlib import Path

from core.ai_config import load_ai_config, resolve_provider
from core.prompts import load_prompt
from core.retry import retry_with_backoff
from core.logging import get_logger
from core.exceptions import AIConfigError, AITimeoutError

_plugin_dir = Path(__file__).resolve().parent
logger = get_logger("auto_rename")

_VALID_NAME_RE = re.compile(r"^[a-zA-Z_][a-zA-Z_0-9:]*(::[a-zA-Z_][a-zA-Z_0-9:]*)*$")


@dataclass
class RenameOptions:
    provider: Optional[str] = None
    mode: Optional[str] = None
    temperature: Optional[float] = None
    custom_prompt: Optional[str] = None


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
                self._results = target()
                if self._on_complete:
                    self._on_complete(self._results)
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
    for ref in func.callers:
        caller = ref.function
        ctx_lines = []
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

    callees = [ref.name for ref in func.callees]

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
        "address": func.start,
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


def _rename_one(bv, func, prompt_template, llm, options):
    context = _build_context(bv, func)
    prompt = prompt_template.format(**context)

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
    ai_config = load_ai_config()
    provider_config = resolve_provider(ai_config, provider)
    llm = _build_llm(provider_config)
    prompt_template = load_prompt(_plugin_dir, "rename.txt")

    def _warn(attempt, exc):
        logger.warning(
            f"rename attempt {attempt} failed for {func.name} at {func.start:#x}: {exc}"
        )

    def _fail(exc):
        logger.error(
            f"rename failed for {func.name} at {func.start:#x}: {exc}"
        )

    def _run():
        return retry_with_backoff(
            _rename_one,
            args=(bv, func, prompt_template, llm, options),
            on_warning=_warn,
            on_failure=_fail,
        )

    if async_run:
        return _AsyncResult(bv, [func], _run, f"Renaming {func.name}", on_complete=on_complete)

    return _run()


def rename_functions(
    bv, funcs, *, provider=None, mode=None, options=None, progress=None, cancel=None, async_run=False, on_complete=None
):
    def _run():
        ai_config = load_ai_config()
        provider_config = resolve_provider(ai_config, provider)
        llm = _build_llm(provider_config)
        prompt_template = load_prompt(_plugin_dir, "rename.txt")

        settings = bv.settings if hasattr(bv, "settings") else None
        parallel = False
        max_workers = 3
        if settings:
            parallel = settings.get_bool("auto_rename.parallel")
            max_workers = settings.get_integer("auto_rename.concurrency")

        if parallel:
            import concurrent.futures

            results = []
            with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as pool:
                future_map = {
                    pool.submit(retry_with_backoff, _rename_one, args=(bv, f, prompt_template, llm, options)): f
                    for f in funcs
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
                    if progress:
                        progress(i + 1, len(funcs))
            return results

        results = []
        for i, func in enumerate(funcs):
            if cancel and cancel():
                break
            result = rename_function(bv, func, provider=provider, options=options)
            results.append(result)
            if progress:
                progress(i + 1, len(funcs))
        return results

    if async_run:
        return _AsyncResult(bv, funcs, _run, f"Renaming {len(funcs)} functions", on_complete=on_complete)
    return _run()


def rename_all(bv, *, provider=None, mode=None, options=None, progress=None, cancel=None, async_run=False, on_complete=None):
    funcs = [f for f in bv.functions if _is_auto_named(f)]
    return rename_functions(bv, funcs, provider=provider, options=options, progress=progress, cancel=cancel, async_run=async_run, on_complete=on_complete)


def rename_filtered(bv, pattern, *, provider=None, mode=None, options=None, progress=None, cancel=None, async_run=False, on_complete=None):
    import re
    compiled = re.compile(pattern)
    funcs = [f for f in bv.functions if _is_auto_named(f) and compiled.match(f.name)]
    return rename_functions(bv, funcs, provider=provider, options=options, progress=progress, cancel=cancel, async_run=async_run, on_complete=on_complete)


def help():
    print("""auto-rename API
---------------
rename_function(bv, func, *, provider=None, mode=None, options=None) -> RenameResult
    Rename a single function based on its disassembly and context.

rename_functions(bv, funcs, *, provider=None, mode=None, options=None, progress=None, cancel=None) -> list[RenameResult]
    Rename multiple functions in batch.

rename_all(bv, *, provider=None, mode=None, options=None, progress=None, cancel=None) -> list[RenameResult]
    Rename all auto-named functions in the binary.

rename_filtered(bv, pattern, *, provider=None, mode=None, options=None, progress=None, cancel=None) -> list[RenameResult]
    Rename functions matching a regex pattern.

Types:
    RenameResult(address: int, old_name: str, new_name: str | None, reasoning: str | None, error: str | None)
    RenameOptions(provider: str | None, mode: str | None, temperature: float | None, custom_prompt: str | None)
""")