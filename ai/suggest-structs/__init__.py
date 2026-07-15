import sys
from pathlib import Path

_plugin_dir = Path(__file__).parent.resolve()
_deps = _plugin_dir / ".deps"
if _deps.is_dir() and str(_deps) not in sys.path:
    sys.path.insert(0, str(_deps))

from binaryninja import PluginCommand
from binaryninja.interaction import show_message_box, MultilineTextField, get_form_input
from binaryninja.mainthread import execute_on_main_thread
from .core.logging import get_logger
from .core.settings import register_setting
from .core.tags import create_tag_type
from .core.ai_config import load_ai_config, resolve_provider

from . import api

logger = get_logger("suggest_structs")

_TAG_TYPE_NAME = "AI Struct"


def _hlil_var_at(bv, addr):
    """Best-effort: the pointer-typed HLIL variable whose def/use is
    closest to `addr` in its containing function, for is_valid gating and
    to resolve which variable "Suggest Struct" targets."""
    funcs = bv.get_functions_containing(addr)
    if not funcs:
        return None, None
    func = funcs[0]
    if not func.hlil:
        return func, None
    best = None
    best_dist = None
    for block in func.hlil:
        if block is None:
            continue
        for instr in block:
            var = getattr(instr, "var", None) if hasattr(instr, "var") else None
            if var is None:
                continue
            t = var.type
            if t is None or "*" not in str(t):
                continue
            dist = abs(instr.address - addr)
            if best_dist is None or dist < best_dist:
                best, best_dist = var, dist
    return func, best


def _apply_results(bv, results, tag_type_name):
    successes = sum(1 for r in results if r.applied)
    failures = sum(1 for r in results if r.error)
    for r in results:
        if r.applied:
            logger.info(f"applied struct {r.struct_name} to {r.var_name} at {r.address:#x}")
        elif r.error:
            logger.warning(f"failed to suggest struct at {r.address:#x}: {r.error}")
    msg = f"Applied {successes} struct(s)"
    if failures:
        msg += f", {failures} failed (see log)"
    show_message_box("Suggest Structs", msg)


def _show_preview_and_apply(bv, func, var, result, tag_type_name):
    """Runs on the main thread: pop the editable free-text C-syntax
    preview (ADR-0027 -- BN's native type editor has no programmatic
    pre-fill API), apply on accept, do nothing on cancel."""
    if result.error:
        show_message_box("Suggest Structs", f"Failed to suggest struct: {result.error}")
        return

    field = MultilineTextField("Struct definition (edit before applying):", result.definition)
    if not get_form_input([field], "Suggest Struct — Preview"):
        return  # user cancelled

    bv.begin_undo_actions()
    applied = api.apply_definition(bv, func, var, field.result, tag_type_name)
    bv.commit_undo_actions()

    if applied.error:
        show_message_box("Suggest Structs", f"Failed to apply struct: {applied.error}")
    else:
        show_message_box("Suggest Structs", f"Applied struct {applied.struct_name} to {var.name if var else '(range)'}")


def _suggest_current(bv, addr):
    func, var = _hlil_var_at(bv, addr)
    if func is None or var is None:
        show_message_box("Suggest Structs", "No pointer variable found near the cursor.")
        return
    tag_type = create_tag_type(bv, _TAG_TYPE_NAME, icon="")

    def on_complete(result):
        # multi mode applies live during its own session (see agent.py) --
        # only single mode needs the preview-then-apply step here.
        if result.error:
            logger.warning(f"suggest failed for {var.name} at {func.start:#x}: {result.error}")
            show_message_box("Suggest Structs", f"Failed: {result.error}")
        elif result.applied:
            show_message_box("Suggest Structs", f"Applied struct {result.struct_name} to {var.name}")
        else:
            execute_on_main_thread(lambda: _show_preview_and_apply(bv, func, var, result, tag_type))

    api.suggest_struct(
        bv, func.start, var_name=var.name, async_run=True, on_complete=on_complete,
        tag_type_name=tag_type,
    )


def _suggest_selection(bv, addr, length):
    if length <= 0:
        show_message_box("Suggest Structs", "No selection.")
        return
    tag_type = create_tag_type(bv, _TAG_TYPE_NAME, icon="")
    func, _ = _hlil_var_at(bv, addr)

    def on_complete(result):
        if result.applied:
            show_message_box("Suggest Structs", f"Applied struct {result.struct_name}")
            return
        if result.error:
            show_message_box("Suggest Structs", f"Failed: {result.error}")
            return
        execute_on_main_thread(lambda: _show_preview_and_apply(bv, func, None, result, tag_type))

    api.suggest_struct_from_range(
        bv, addr, length, async_run=True, on_complete=on_complete, tag_type_name=tag_type,
    )


def _suggest_all(bv, addr):
    tag_type = create_tag_type(bv, _TAG_TYPE_NAME, icon="")

    def on_complete(results):
        bv.commit_undo_actions()
        _apply_results(bv, results, tag_type)

    bv.begin_undo_actions()
    api.suggest_all(bv, async_run=True, on_complete=on_complete, tag_type_name=tag_type)


def _is_valid_pointer_var(bv, addr):
    _func, var = _hlil_var_at(bv, addr)
    return var is not None


def _is_valid_selection(bv, addr, length):
    return length > 0


register_setting(
    "suggest_structs.provider",
    "Provider name from ai-config.json (empty = default)",
    "",
)
register_setting(
    "suggest_structs.mode",
    "Agent mode: single (langchain) or multi (deepagents)",
    "multi",
)
register_setting(
    "suggest_structs.config_path",
    "Path to complex config file",
    str(Path.home() / ".binaryninja" / "suggest-structs.json"),
)
register_setting(
    "suggest_structs.confidence_threshold",
    "Type.confidence at/above which a variable is skipped as already-typed during batch sweep",
    255,
)
register_setting(
    "suggest_structs.agent_max_steps",
    "Multi-mode agent tool-call budget per session",
    12,
)
register_setting(
    "suggest_structs.agent_max_structs_per_session",
    "Cap on submit_struct calls per multi-mode agent session",
    8,
)

PluginCommand.register_for_address(
    "Suggest Structs\\Suggest Struct",
    "Suggest a struct for the pointer variable near the cursor using AI",
    _suggest_current,
    _is_valid_pointer_var,
)
PluginCommand.register_for_range(
    "Suggest Structs\\Suggest Struct (Selection)",
    "Suggest a struct for the selected byte range using AI",
    _suggest_selection,
    _is_valid_selection,
)
PluginCommand.register_for_address(
    "Suggest Structs\\Suggest Struct (Batch)",
    "Suggest structs for all candidate pointer variables and untyped globals using AI",
    _suggest_all,
)

try:
    ai_config = load_ai_config()
    provider_name = resolve_provider(ai_config).get("model", "unknown")
    logger.info(f"suggest-structs loaded, provider: {provider_name}")
except Exception as e:
    logger.warning(f"suggest-structs loaded, but AI config error: {e}")
