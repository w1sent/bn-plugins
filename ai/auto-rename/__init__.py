import sys
from pathlib import Path

_plugin_dir = Path(__file__).resolve().parent
_deps = _plugin_dir / ".deps"
if _deps.is_dir() and str(_deps) not in sys.path:
    sys.path.insert(0, str(_deps))

from binaryninja import PluginCommand, TagType
from binaryninja.interaction import show_message_box
from core.logging import get_logger
from core.settings import register_setting
from core.tags import create_tag_type, tag_item
from core.ai_config import load_ai_config, resolve_provider

from . import api

logger = get_logger("auto_rename")

_TAG_TYPE_NAME = "AI Renamed"

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


def _apply_results(bv, results, tag_type):
    successes = 0
    failures = 0
    for r in results:
        if r.new_name:
            successes += 1
            logger.info(f"renamed {r.old_name} at {r.address:#x} -> {r.new_name}")
            if r.reasoning:
                logger.info(f"  reason: {r.reasoning}")
            if tag_type:
                tag_item(bv, r.address, _TAG_TYPE_NAME, f"renamed from {r.old_name}")
        else:
            failures += 1
            logger.warning(f"failed to rename {r.old_name} at {r.address:#x}: {r.error}")
    msg = f"Renamed {successes} function(s)"
    if failures:
        msg += f", {failures} failed (see log)"
    show_message_box("Auto Rename", msg)


def _run_rename_batch(bv, funcs, tag_type, title):
    if not funcs:
        show_message_box("Auto Rename", "No auto-named functions found.")
        return

    def on_complete(results):
        bv.commit_undo_actions()
        _apply_results(bv, results, tag_type)

    bv.begin_undo_actions()
    api.rename_functions(
        bv, funcs, async_run=True, on_complete=on_complete
    )


def _rename_current(bv):
    func = bv.get_current_function()
    if not func:
        show_message_box("Auto Rename", "No function selected.")
        return
    tag_type = create_tag_type(bv, _TAG_TYPE_NAME, icon="", color="#00cc66")
    _run_rename_batch(bv, [func], tag_type, "Renaming function")


def _rename_selection(bv):
    funcs = bv.get_selected_functions()
    if not funcs:
        show_message_box("Auto Rename", "No functions selected.")
        return
    tag_type = create_tag_type(bv, _TAG_TYPE_NAME, icon="", color="#00cc66")
    _run_rename_batch(bv, funcs, tag_type, "Renaming selection")


def _rename_all(bv):
    auto_named = [f for f in bv.functions if _is_auto_named(f)]
    tag_type = create_tag_type(bv, _TAG_TYPE_NAME, icon="", color="#00cc66")
    _run_rename_batch(bv, auto_named, tag_type, "Renaming all functions")


def _rename_filtered(bv):
    from binaryninja.interaction import get_text_line_input

    pattern = get_text_line_input(
        "Regex pattern (matches function names):", "Auto Rename (Filtered)"
    )
    if not pattern:
        return
    import re

    try:
        compiled = re.compile(pattern)
    except re.error as e:
        show_message_box("Auto Rename", f"Invalid regex: {e}")
        return
    funcs = [
        f
        for f in bv.functions
        if _is_auto_named(f) and compiled.match(f.name)
    ]
    tag_type = create_tag_type(bv, _TAG_TYPE_NAME, icon="", color="#00cc66")
    _run_rename_batch(bv, funcs, tag_type, "Renaming filtered functions")


def _is_valid_func(bv):
    return bv.get_current_function() is not None


def _is_valid_selection(bv):
    return len(bv.get_selected_functions()) > 0


register_setting(
    "auto_rename.provider",
    "Provider name from ai-config.json (empty = default)",
    "",
)
register_setting(
    "auto_rename.mode",
    "Agent mode: single or multi",
    "single",
)
register_setting(
    "auto_rename.config_path",
    "Path to complex config file",
    str(Path.home() / ".binaryninja" / "auto-rename.json"),
)
register_setting(
    "auto_rename.parallel",
    "Process functions in parallel",
    False,
)
register_setting(
    "auto_rename.concurrency",
    "Max concurrent LLM calls",
    3,
)

PluginCommand.register_for_function(
    "Auto Rename", "Rename function using AI", _rename_current, _is_valid_func
)
PluginCommand.register_for_function(
    "Auto Rename (Filtered)",
    "Rename functions matching a regex pattern",
    _rename_filtered,
    _is_valid_func,
)
PluginCommand.register_for_selection(
    "Auto Rename (Selection)",
    "Rename selected functions using AI",
    _rename_selection,
    _is_valid_selection,
)
PluginCommand.register(
    "Auto Rename All", "Rename all auto-named functions using AI", _rename_all
)

try:
    ai_config = load_ai_config()
    provider_name = resolve_provider(ai_config).get("model", "unknown")
    logger.info(f"auto-rename loaded, provider: {provider_name}")
except Exception as e:
    logger.warning(f"auto-rename loaded, but AI config error: {e}")