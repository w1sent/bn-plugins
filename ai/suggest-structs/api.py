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
from .core import llm_debug

_plugin_dir = Path(__file__).parent.resolve()
logger = get_logger("suggest_structs")
_PLUGIN_NAME = "suggest_structs"


def _debug_logging_enabled(bv):
    return llm_debug.is_enabled("suggest_structs.debug_logging", bv)

_DEFAULT_PLUGIN_CONFIG_PATH = Path.home() / ".binaryninja" / "suggest-structs.json"
_DEFAULT_PLUGIN_CONFIG = {
    "custom_prompt": None,
    "custom_agent_prompt": None,
    "temperature": 0.1,
    "backoff_steps": [1, 2, 4, 8],
}

_DATA_NAME_PREFIXES = ("data_", "byte_", "word_", "dword_", "unk_")
_STRUCT_NAME_RE = re.compile(r"\bstruct\s+([A-Za-z_][A-Za-z0-9_]*)")


def _ensure_deps_on_path():
    """Re-assert .deps/ on sys.path from the calling thread.

    See auto-rename's api.py for why this needs to be self-sufficient
    rather than relying on __init__.py's module-load-time setup.
    """
    deps = _plugin_dir / ".deps"
    if deps.is_dir() and str(deps) not in sys.path:
        sys.path.insert(0, str(deps))


@dataclass
class StructOptions:
    provider: Optional[str] = None
    mode: Optional[str] = None
    temperature: Optional[float] = None
    custom_prompt: Optional[str] = None
    confidence_threshold: Optional[int] = None
    agent_max_steps: Optional[int] = None
    agent_max_structs_per_session: Optional[int] = None


@dataclass
class StructResult:
    address: int
    var_name: Optional[str] = None
    struct_name: Optional[str] = None
    definition: Optional[str] = None
    applied: bool = False
    reasoning: Optional[str] = None
    error: Optional[str] = None


class _AsyncResult:
    def __init__(self, bv, target, title, on_complete=None):
        from binaryninja import BackgroundTask

        self._results = []
        self._done = threading.Event()
        self._task = BackgroundTask(title, can_cancel=True)
        self._cancel = False
        self._on_complete = on_complete

        def _run():
            try:
                self._results = target(self._set_progress, self._is_cancelled)
                if self._on_complete:
                    self._on_complete(self._results)
            finally:
                self._done.set()
                self._task.finish()

        thread = threading.Thread(target=_run, daemon=True)
        thread.start()

    def _set_progress(self, text):
        self._task.progress = text

    def _is_cancelled(self):
        return self._cancel or self._task.cancelled

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


# ---------------------------------------------------------------------------
# Deterministic skeleton extraction (trigger 1) -- offsets/sizes/gaps are
# computed here so the LLM never has to invent an offset that doesn't match
# a real access; the skeleton is handed to the LLM as advisory context, not
# a hard constraint (it may still deviate if surrounding context disagrees
# with what BN's own analysis inferred).
# ---------------------------------------------------------------------------


@dataclass
class SkeletonField:
    offset: int
    size: int
    c_type: str = "unknown"
    note: str = ""


def _hlil_var_for(func, var_name):
    if not func.hlil:
        return None
    for v in func.hlil.vars:
        if v.name == var_name:
            return v
    return None


def _var_offset_from_address_expr(expr, var_name):
    """If `expr` (an HLIL_DEREF's address operand) is `var` or a
    `var + const` / `const + var` add, return the offset; else None.

    This is the common case for a pointer with no struct type yet: BN
    represents `*(int32_t*)(p + 4)` as HLIL_DEREF(HLIL_ADD(HLIL_VAR(p),
    HLIL_CONST(4))), NOT HLIL_DEREF_FIELD -- that operation only appears
    once BN (or the user) already has a struct/array type on the pointer,
    which is exactly what suggest-structs is trying to produce in the
    first place."""
    from binaryninja.highlevelil import HighLevelILOperation

    op = getattr(expr, "operation", None)
    if op == HighLevelILOperation.HLIL_VAR:
        v = getattr(expr, "var", None)
        if v is not None and v.name == var_name:
            return 0
        return None
    if op == HighLevelILOperation.HLIL_ADD:
        left, right = expr.left, expr.right
        for a, b in ((left, right), (right, left)):
            a_op = getattr(a, "operation", None)
            a_var = getattr(a, "var", None) if a_op == HighLevelILOperation.HLIL_VAR else None
            b_const = getattr(b, "constant", None)
            if a_var is not None and a_var.name == var_name and isinstance(b_const, int):
                return b_const
    return None


def extract_skeleton(bv, func, var):
    """Deterministically walk `var`'s HLIL uses to build an advisory list
    of (offset, size, type) fields from real offset accesses. Best-effort:
    unions/overlaps are reported as separate fields rather than resolved."""
    from binaryninja.highlevelil import HighLevelILOperation

    fields = {}
    if not func.hlil:
        return []

    for block in func.hlil:
        if block is None:
            continue
        for instr in block:
            # shallow=False: without it, traverse() only visits top-level
            # operands of `instr` and misses offset accesses nested inside
            # compound expressions (e.g. `foo->bar->baz`). The callback
            # must return the node itself (or None to skip it) -- traverse()
            # yields whatever the callback returns *directly*, it does not
            # flatten a list return, so `lambda e: [e]` (an earlier version
            # of this code) silently yielded one-element lists instead of
            # instructions and never matched anything.
            for expr in instr.traverse(lambda e: e, shallow=False):
                if expr is None:
                    continue
                op = getattr(expr, "operation", None)

                if op == HighLevelILOperation.HLIL_DEREF:
                    offset = _var_offset_from_address_expr(expr.src, var.name)
                    if offset is None:
                        continue
                    size = getattr(expr, "size", 0) or bv.address_size
                elif op == HighLevelILOperation.HLIL_DEREF_FIELD:
                    src = getattr(expr, "src", None)
                    src_var = getattr(src, "var", None)
                    if src_var is None or src_var.name != var.name:
                        continue
                    offset = getattr(expr, "offset", 0) or 0
                    size = getattr(expr, "size", 0) or bv.address_size
                elif op == HighLevelILOperation.HLIL_ARRAY_INDEX:
                    # HLIL_ARRAY_INDEX has no `.offset` -- `result[1]` means
                    # "the 2nd element of whatever result points to", so the
                    # byte offset is index * element_size, not index itself.
                    src = getattr(expr, "src", None)
                    src_var = getattr(src, "var", None)
                    if src_var is None or src_var.name != var.name:
                        continue
                    index_expr = getattr(expr, "index", None)
                    index_const = getattr(index_expr, "constant", None)
                    if not isinstance(index_const, int):
                        continue
                    size = getattr(expr, "size", 0) or bv.address_size
                    offset = index_const * size
                else:
                    continue

                c_type = str(expr.expr_type) if getattr(expr, "expr_type", None) else "unknown"
                key = offset
                if key not in fields or fields[key].size < size:
                    fields[key] = SkeletonField(offset=offset, size=size, c_type=c_type)

    return [fields[k] for k in sorted(fields)]


def _skeleton_to_text(skeleton):
    if not skeleton:
        return "(no offset accesses found -- infer layout entirely from context)"
    lines = []
    for f in skeleton:
        lines.append(f"  +{f.offset:#x} (size {f.size}): {f.c_type}")
    return "\n".join(lines)


def _build_var_context(bv, func, var, skeleton):
    hlil_lines = []
    if func.hlil:
        for block in func.hlil:
            if block is None:
                continue
            for instr in block:
                hlil_lines.append(f"  {instr.address:#x}: {instr}")
    disassembly = "\n".join(hlil_lines) if hlil_lines else "(no HLIL available)"

    string_refs = []
    data_refs = []
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
                    for ref_addr in bv.get_data_refs(const):
                        data = bv.read(ref_addr, 16)
                        if data:
                            hex_preview = " ".join(f"{b:02x}" for b in data)
                            data_refs.append(f"  {ref_addr:#x}: {hex_preview}")

    existing_types = "\n".join(
        f"  {name}" for name in list(bv.type_names)[:200]
    ) or "(none)"

    return {
        "function_name": func.name,
        "address": f"{func.start:#x}",
        "var_name": var.name if var else "(range)",
        "skeleton": _skeleton_to_text(skeleton),
        "string_refs": "\n".join(string_refs) or "(none)",
        "data_refs": "\n".join(data_refs) or "(none)",
        "disassembly": disassembly,
        "existing_types": existing_types,
    }


def _build_range_context(bv, start, length, skeleton):
    """Context for trigger 2 when `start` isn't inside any function --
    the common case for a global/static blob, or any address selected
    outside code. No HLIL/function to pull disassembly or string/data
    refs *from*; instead this looks at what points *at* the range."""
    data = bv.read(start, length) or b""
    hex_preview = " ".join(f"{b:02x}" for b in data) or "(unreadable)"

    ref_lines = []
    for ref in list(bv.get_code_refs(start))[:20]:
        ref_func = getattr(ref, "function", None)
        ref_lines.append(f"  code ref from {ref_func.name if ref_func else '?'} at {ref.address:#x}")
    for ref_addr in list(bv.get_data_refs(start))[:20]:
        ref_lines.append(f"  data ref from {ref_addr:#x}")

    sym = bv.get_symbol_at(start)
    existing_types = "\n".join(
        f"  {name}" for name in list(bv.type_names)[:200]
    ) or "(none)"

    return {
        "function_name": "(none -- raw memory region, not inside any function)",
        "address": f"{start:#x}",
        "var_name": sym.name if sym else "(range)",
        "skeleton": _skeleton_to_text(skeleton),
        "string_refs": "(n/a -- no containing function to scan)",
        "data_refs": "\n".join(ref_lines) or "(none found pointing at this range)",
        "disassembly": f"raw bytes at {start:#x} (length {length}): {hex_preview}",
        "existing_types": existing_types,
    }


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


def _apply_temperature(provider_config, temperature):
    if temperature is None or provider_config.get("parameters", {}).get("temperature") is not None:
        return provider_config
    provider_config = dict(provider_config)
    provider_config["parameters"] = dict(provider_config.get("parameters", {}))
    provider_config["parameters"]["temperature"] = temperature
    return provider_config


def _resolve_plugin_config(bv, options):
    """Load suggest-structs.json, creating it with defaults on first use
    (ADR-0026). `options` fields, when set, take precedence over the file.
    Note: confidence_threshold / agent_max_steps / agent_max_structs_per_session
    are BN native Settings, not part of this file (see TODO.md)."""
    from binaryninja import Settings

    settings = Settings()
    config_path = settings.get_string("suggest_structs.config_path", resource=bv) or str(
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


def _resolve_bn_settings(bv, options):
    from binaryninja import Settings

    settings = Settings()
    threshold = (
        options.confidence_threshold
        if options and options.confidence_threshold is not None
        else settings.get_integer("suggest_structs.confidence_threshold", resource=bv)
    )
    max_steps = (
        options.agent_max_steps
        if options and options.agent_max_steps is not None
        else settings.get_integer("suggest_structs.agent_max_steps", resource=bv)
    )
    max_structs = (
        options.agent_max_structs_per_session
        if options and options.agent_max_structs_per_session is not None
        else settings.get_integer("suggest_structs.agent_max_structs_per_session", resource=bv)
    )
    return threshold or 255, max_steps or 12, max_structs or 8


def _resolve_mode(bv, options):
    from binaryninja import Settings

    settings = Settings()
    return (options.mode if options else None) or settings.get_string(
        "suggest_structs.mode", resource=bv
    ) or "multi"


def _existing_type_names(bv):
    return set(bv.type_names)


def _apply_definition(bv, func, var, definition, tag_type_name, data_addr=None):
    """Parse `definition` (C struct text, possibly multiple structs) and
    apply the last-defined struct to its target. Returns
    (struct_name, applied: bool, error: Optional[str]).

    Exactly one of `var` (an HLIL variable -- gets the struct's *pointer*
    type, since a variable holds a pointer to the struct) or `data_addr`
    (a global address -- gets the struct's *value* type directly, since
    the global memory region itself is the struct) should be given. If
    neither is given, the type(s) are still defined/reused but nothing is
    applied anywhere (used by preview flows that apply separately)."""
    from .core.tags import tag_item

    try:
        parsed = bv.parse_types_from_string(definition)
    except Exception as e:
        return None, False, f"failed to parse struct definition: {e}"

    types = parsed.types
    if not types:
        return None, False, "LLM produced no struct definitions"

    # Dict preserves insertion/parse order; the prompt instructs the LLM to
    # put dependencies first and the struct meant for the target last, so
    # the last entry is the one applied. See prompts/suggest_struct.txt.
    existing = _existing_type_names(bv)
    struct_name = None
    for name, t in types.items():
        struct_name = name
        if name in existing:
            continue
        bv.define_user_type(name, t)

    if var is not None and struct_name:
        try:
            ptr_type = bv.parse_type_string(f"struct {struct_name}*")[0]
            func.create_user_var(var, ptr_type, var.name)
            if tag_type_name:
                tag_item(bv, func.start, tag_type_name, f"applied struct {struct_name} to {var.name}")
        except Exception as e:
            return struct_name, False, f"parsed struct but failed to apply to variable: {e}"
    elif data_addr is not None and struct_name:
        try:
            value_type = bv.parse_type_string(f"struct {struct_name}")[0]
            bv.define_user_data_var(data_addr, value_type)
            if tag_type_name:
                tag_item(bv, data_addr, tag_type_name, f"applied struct {struct_name} at {data_addr:#x}")
        except Exception as e:
            return struct_name, False, f"parsed struct but failed to apply to data var: {e}"

    return struct_name, True, None


def _single_mode_suggest(
    bv, func, var, skeleton, prompt_template, llm, start=None, length=None,
    provider_config=None, debug=False,
):
    if func is not None:
        context = _build_var_context(bv, func, var, skeleton)
    else:
        context = _build_range_context(bv, start, length, skeleton)
    # $-style substitution, not str.format(): C struct examples in the
    # template contain literal braces that str.format() would misparse.
    prompt = string.Template(prompt_template).safe_substitute(context)
    if debug:
        llm_debug.log_request(_PLUGIN_NAME, provider_config, prompt)
    response = llm.invoke(prompt)
    content = response.content.strip()
    if content.startswith("```"):
        content = content.split("\n", 1)[-1]
        content = content.rsplit("\n```", 1)[0]
    return content


def _suggest_one(bv, addr, var_name, *, provider, options, tag_type_name):
    """Trigger 1: `var_name` must name a real HLIL variable in the function
    containing `addr` -- callers (both __init__.py's cursor-detection and
    the batch dispatcher below) are responsible for resolving which
    variable they mean before calling this. There is no auto-detection
    here; a missing/unresolvable `var_name` is an error, not a guess."""
    func = None
    var = None
    funcs = bv.get_functions_containing(addr)
    if funcs:
        func = funcs[0]
        if var_name:
            var = _hlil_var_for(func, var_name)

    if func is None:
        return StructResult(address=addr, var_name=var_name, error="no function containing address")
    if var_name and var is None:
        return StructResult(
            address=addr, var_name=var_name,
            error=f"no HLIL variable named {var_name!r} in function at {func.start:#x}",
        )

    skeleton = extract_skeleton(bv, func, var) if var is not None else []

    custom_prompt, temperature, backoff_steps = _resolve_plugin_config(bv, options)
    ai_config = load_ai_config()
    provider_config = _apply_temperature(resolve_provider(ai_config, provider), temperature)
    mode = _resolve_mode(bv, options)

    def _warn(attempt, exc):
        logger.warning(f"suggest attempt {attempt} failed for {var_name} at {addr:#x}: {exc}")

    def _fail(exc):
        logger.error(f"suggest failed for {var_name} at {addr:#x}: {exc}")

    try:
        if mode == "multi":
            from .agent import run_agent_session

            threshold, max_steps, max_structs = _resolve_bn_settings(bv, options)
            definition, applied_names, error = run_agent_session(
                bv,
                func,
                var,
                skeleton,
                provider_config=provider_config,
                custom_prompt=(options.custom_prompt if options else None)
                or _resolve_plugin_config(bv, options)[0],
                max_steps=max_steps,
                max_structs=max_structs,
                tag_type_name=tag_type_name,
                debug=_debug_logging_enabled(bv),
            )
            if error:
                return StructResult(address=addr, var_name=var_name, error=error)
            return StructResult(
                address=addr,
                var_name=var_name,
                struct_name=", ".join(applied_names) if applied_names else None,
                definition=definition,
                applied=bool(applied_names),
            )

        llm = _build_llm(provider_config)
        prompt_template = custom_prompt or load_prompt(_plugin_dir, "suggest_struct.txt")
        definition = retry_with_backoff(
            _single_mode_suggest,
            args=(bv, func, var, skeleton, prompt_template, llm, None, None, provider_config, _debug_logging_enabled(bv)),
            backoff_steps=backoff_steps,
            on_warning=_warn,
            on_failure=_fail,
        )
        return StructResult(
            address=addr, var_name=var_name, definition=definition, applied=False
        )
    except Exception as e:
        return StructResult(address=addr, var_name=var_name, error=str(e))


def suggest_struct(
    bv, addr, *, var_name=None, provider=None, mode=None, options=None,
    async_run=False, on_complete=None, tag_type_name=None,
):
    """Suggest a struct for the pointer variable at `addr` (trigger 1).

    Returns StructResult when sync, _AsyncResult when async_run=True.
    In single mode, `definition` is unapplied C struct text meant for
    preview; apply it via `apply_definition`. In multi mode the agent
    applies directly during its session (see agent.py) and `applied`
    reflects that.
    """
    if options is None:
        options = StructOptions()
    if mode is not None:
        options.mode = mode

    def _run(set_progress=None, is_cancelled=None):
        if set_progress:
            set_progress(f"Suggesting struct at {addr:#x}...")
        return _suggest_one(
            bv, addr, var_name, provider=provider, options=options, tag_type_name=tag_type_name
        )

    if async_run:
        return _AsyncResult(bv, _run, f"Suggesting struct at {addr:#x}", on_complete=on_complete)
    return _run()


def apply_definition(bv, func, var, definition, tag_type_name=None, data_addr=None):
    """Apply previously-previewed/edited C struct text to `var` (a
    function-local pointer variable) or `data_addr` (a global/memory-region
    address, when there's no variable -- e.g. the range-selection trigger).
    Used by __init__.py after the user accepts the preview popup (single
    mode)."""
    struct_name, applied, error = _apply_definition(
        bv, func, var, definition, tag_type_name, data_addr=data_addr
    )
    return StructResult(
        address=data_addr if data_addr is not None else func.start,
        var_name=var.name if var else None,
        struct_name=struct_name,
        definition=definition,
        applied=applied,
        error=error,
    )


def suggest_struct_from_range(
    bv, start, length, *, provider=None, mode=None, options=None,
    async_run=False, on_complete=None, tag_type_name=None,
):
    """Suggest a struct for a raw byte range (trigger 2): seed a struct
    sized to `length`, then run the same LLM refinement `suggest_struct`
    uses, sharing that code path rather than duplicating it."""
    if options is None:
        options = StructOptions()
    if mode is not None:
        options.mode = mode

    def _run(set_progress=None, is_cancelled=None):
        if set_progress:
            set_progress(f"Seeding struct for range {start:#x}+{length:#x}...")
        seed = SkeletonField(offset=0, size=length, c_type=f"uint8_t[{length}]", note="range seed")
        # `func` is optional here, unlike trigger 1: the whole point of a
        # range-based suggestion is to cover addresses with no containing
        # function -- globals, .data/.bss blobs, anything selected outside
        # code. When present it's used for richer context (real HLIL,
        # string/data refs); when absent, _build_range_context (called via
        # _single_mode_suggest / run_agent_session) covers the target with
        # just its raw bytes and inbound references instead.
        func = None
        funcs = bv.get_functions_containing(start)
        if funcs:
            func = funcs[0]

        custom_prompt, temperature, backoff_steps = _resolve_plugin_config(bv, options)
        ai_config = load_ai_config()
        provider_config = _apply_temperature(resolve_provider(ai_config, provider), temperature)
        mode_resolved = _resolve_mode(bv, options)

        if mode_resolved == "multi":
            from .agent import run_agent_session

            threshold, max_steps, max_structs = _resolve_bn_settings(bv, options)
            definition, applied_names, error = run_agent_session(
                bv, func, None, [seed], provider_config=provider_config,
                custom_prompt=custom_prompt, max_steps=max_steps,
                max_structs=max_structs, tag_type_name=tag_type_name,
                start=start, debug=_debug_logging_enabled(bv),
            )
            if error:
                return StructResult(address=start, error=error)
            return StructResult(
                address=start,
                struct_name=", ".join(applied_names) if applied_names else None,
                definition=definition,
                applied=bool(applied_names),
            )

        llm = _build_llm(provider_config)
        prompt_template = custom_prompt or load_prompt(_plugin_dir, "suggest_struct.txt")
        definition = retry_with_backoff(
            _single_mode_suggest,
            args=(bv, func, None, [seed], prompt_template, llm, start, length, provider_config, _debug_logging_enabled(bv)),
            backoff_steps=backoff_steps,
        )
        return StructResult(address=start, definition=definition, applied=False)

    if async_run:
        return _AsyncResult(
            bv, _run, f"Suggesting struct for range {start:#x}", on_complete=on_complete
        )
    return _run()


def _is_pointer_var(var):
    t = var.type
    return t is not None and "*" in str(t)


def _is_still_default(bv, func, var, threshold):
    from binaryninja import Function

    if func.is_var_user_defined(var):
        return False
    return var.type is None or var.type.confidence < threshold


def _candidate_vars(bv, threshold):
    """Trigger 3 enumeration: pointer-typed local/param HLIL vars below
    `threshold`, plus data_<addr>-named globals below `threshold`."""
    candidates = []
    for func in bv.functions:
        if not func.hlil:
            continue
        for var in func.hlil.vars:
            if not _is_pointer_var(var):
                continue
            if not _is_still_default(bv, func, var, threshold):
                continue
            candidates.append((func.start, var.name))

    for addr, data_var in bv.data_vars.items():
        sym = bv.get_symbol_at(addr)
        name = sym.name if sym else f"data_{addr:#x}"
        if not any(name.startswith(p) for p in _DATA_NAME_PREFIXES):
            continue
        if data_var.type is not None and data_var.type.confidence >= threshold:
            continue
        candidates.append((addr, None))

    return candidates


def _suggest_batch_item(bv, addr, var_name, *, provider, options, tag_type_name):
    """Dispatch one batch candidate to the right trigger and apply the
    result directly (batch mode has no preview step). `var_name` is set
    only for local pointer-variable candidates (trigger 1); candidates
    with `var_name is None` are globals from `_candidate_vars`, which need
    trigger 2 (range-seeded to the data var's own length) since there's no
    HLIL variable to analyze -- see TODO.md "Trigger 3 (batch sweep)"."""
    if var_name is not None:
        result = _suggest_one(
            bv, addr, var_name, provider=provider, options=options, tag_type_name=tag_type_name
        )
        if result.definition and not result.applied and not result.error:
            funcs = bv.get_functions_containing(addr)
            if funcs:
                func = funcs[0]
                var = _hlil_var_for(func, var_name)
                struct_name, applied, error = _apply_definition(
                    bv, func, var, result.definition, tag_type_name
                )
                result.struct_name = struct_name
                result.applied = applied
                result.error = error
        return result

    data_var = bv.data_vars.get(addr)
    length = data_var.type.width if data_var is not None and data_var.type is not None else 1
    result = suggest_struct_from_range(
        bv, addr, max(length, 1), provider=provider, options=options, tag_type_name=tag_type_name
    )
    if result.definition and not result.applied and not result.error:
        struct_name, applied, error = _apply_definition(
            bv, None, None, result.definition, tag_type_name, data_addr=addr
        )
        result.struct_name = struct_name
        result.applied = applied
        result.error = error
    return result


def suggest_structs(
    bv, addrs, *, provider=None, mode=None, options=None,
    progress=None, cancel=None, async_run=False, on_complete=None,
    tag_type_name=None,
):
    """Suggest structs for multiple (address, var_name) pairs or plain
    addresses (batch use, trigger 3). Applies directly, no preview."""
    if options is None:
        options = StructOptions()
    if mode is not None:
        options.mode = mode

    items = [a if isinstance(a, tuple) else (a, None) for a in addrs]
    total = len(items)

    def _run(set_progress=None, is_cancelled=None):
        results = []
        for i, (addr, var_name) in enumerate(items):
            if cancel and cancel():
                break
            if is_cancelled and is_cancelled():
                break
            result = _suggest_batch_item(
                bv, addr, var_name, provider=provider, options=options, tag_type_name=tag_type_name
            )
            results.append(result)
            if progress:
                progress(i + 1, total)
            if set_progress:
                label = f"Suggesting structs ({i + 1}/{total})"
                if result.struct_name:
                    label += f": {result.struct_name}"
                set_progress(label)
        return results

    if async_run:
        return _AsyncResult(bv, _run, f"Suggesting {total} structs", on_complete=on_complete)
    return _run()


def suggest_all(
    bv, *, provider=None, mode=None, options=None,
    progress=None, cancel=None, async_run=False, on_complete=None,
    tag_type_name=None,
):
    """Batch-sweep every candidate pointer variable / untyped global
    (trigger 3, see TODO.md)."""
    if options is None:
        options = StructOptions()
    threshold, _max_steps, _max_structs = _resolve_bn_settings(bv, options)
    addrs = _candidate_vars(bv, threshold)
    return suggest_structs(
        bv, addrs, provider=provider, options=options,
        progress=progress, cancel=cancel, async_run=async_run,
        on_complete=on_complete, tag_type_name=tag_type_name,
    )


def help():
    print("""suggest-structs API
--------------------
suggest_struct(bv, addr, *, var_name=None, provider=None, mode=None, options=None) -> StructResult
    Suggest a struct for the pointer variable `var_name` in the function containing
    `addr` (trigger 1: access-pattern analysis). In single mode, `result.definition`
    is unapplied C struct text for preview -- pass it to `apply_definition()` after
    the user accepts. In multi mode the agent applies directly during its session.

apply_definition(bv, func, var, definition, tag_type_name=None) -> StructResult
    Apply previously-suggested (and possibly user-edited) C struct text to `var`.

suggest_struct_from_range(bv, start, length, *, provider=None, mode=None, options=None) -> StructResult
    Suggest a struct for a raw byte range (trigger 2: selection seed + refinement).

suggest_structs(bv, addrs, *, provider=None, mode=None, options=None,
                 progress=None, cancel=None) -> list[StructResult]
    Suggest structs for a list of addresses or (address, var_name) tuples.
    Applies directly (no preview) -- meant for batch use.

suggest_all(bv, *, provider=None, mode=None, options=None,
            progress=None, cancel=None) -> list[StructResult]
    Batch-sweep every candidate pointer variable / untyped global (trigger 3).

Types:
    StructResult(address: int, var_name: str | None, struct_name: str | None,
                 definition: str | None, applied: bool, reasoning: str | None,
                 error: str | None)
    StructOptions(provider: str | None, mode: str | None, temperature: float | None,
                  custom_prompt: str | None, confidence_threshold: int | None,
                  agent_max_steps: int | None, agent_max_structs_per_session: int | None)
""")
