import sys
from pathlib import Path

_plugin_dir = Path(__file__).parent.resolve()
_deps = _plugin_dir / ".deps"
if _deps.is_dir() and str(_deps) not in sys.path:
    sys.path.insert(0, str(_deps))

from binaryninja import PluginCommand
from binaryninja.enums import SymbolType
from binaryninja.interaction import show_message_box, get_choice_input, get_int_input
from .core.logging import get_logger
from .core.settings import register_setting
from .core.tags import create_tag_type, tag_item
from .core.ai_config import load_ai_config, resolve_provider

from . import api
from .ordering import ORDERINGS, OrderingError

logger = get_logger("auto_rename")

_TAG_TYPE_NAME = "AI Renamed"

_IMPORT_SYMBOL_TYPES = (
    SymbolType.ImportedFunctionSymbol,
    SymbolType.ImportAddressSymbol,
    SymbolType.ExternalSymbol,
)


def _is_auto_named(func):
    name = func.name
    symbol = func.symbol
    is_import = symbol is not None and symbol.type in _IMPORT_SYMBOL_TYPES
    return (
        not is_import
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


def _function_at(bv, addr):
    funcs = bv.get_functions_containing(addr)
    return funcs[0] if funcs else None


def _run_rename_batch(bv, funcs, tag_type, title, anchor=None, restrict_to=None, options=None):
    if not funcs:
        show_message_box("Auto Rename", "No auto-named functions found.")
        return

    def on_complete(results):
        bv.commit_undo_actions()
        _apply_results(bv, results, tag_type)

    bv.begin_undo_actions()
    try:
        api.rename_functions(
            bv,
            funcs,
            anchor=anchor,
            restrict_to=restrict_to,
            options=options,
            async_run=True,
            on_complete=on_complete,
        )
    except OrderingError as e:
        bv.commit_undo_actions()
        show_message_box("Auto Rename", f"This ordering requires a function to be selected: {e}")


def _rename_current(bv, func):
    tag_type = create_tag_type(bv, _TAG_TYPE_NAME, icon="")
    _run_rename_batch(bv, [func], tag_type, "Renaming function", anchor=func)


def _rename_selection(bv, addr, length):
    funcs = [f for f in bv.functions if addr <= f.start < addr + length]
    if not funcs:
        show_message_box("Auto Rename", "No functions in the current selection.")
        return
    tag_type = create_tag_type(bv, _TAG_TYPE_NAME, icon="")
    _run_rename_batch(
        bv,
        funcs,
        tag_type,
        "Renaming selection",
        anchor=_function_at(bv, addr) or funcs[0],
        restrict_to=funcs,
    )


def _rename_all(bv, addr):
    auto_named = [f for f in bv.functions if _is_auto_named(f)]
    tag_type = create_tag_type(bv, _TAG_TYPE_NAME, icon="")
    _run_rename_batch(
        bv, auto_named, tag_type, "Renaming all functions", anchor=_function_at(bv, addr)
    )


def _rename_filtered(bv, addr):
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
    tag_type = create_tag_type(bv, _TAG_TYPE_NAME, icon="")
    _run_rename_batch(
        bv, funcs, tag_type, "Renaming filtered functions", anchor=_function_at(bv, addr)
    )


def _rename_all_choose_strategy(bv, addr):
    ordering_idx = get_choice_input(
        "Ordering strategy:", "Auto Rename All (Choose Strategy)", list(ORDERINGS)
    )
    if ordering_idx is None:
        return
    chosen_ordering = ORDERINGS[ordering_idx]

    concurrency_choices = ["sequential", "fixed-pool"]
    concurrency_idx = get_choice_input(
        "Concurrency mode:", "Auto Rename All (Choose Strategy)", concurrency_choices
    )
    if concurrency_idx is None:
        return
    chosen_concurrency = concurrency_choices[concurrency_idx]

    workers = None
    if chosen_concurrency == "fixed-pool":
        workers = get_int_input("Number of workers:", "Auto Rename All (Choose Strategy)")
        if workers is None:
            return

    # One-shot only: this RenameOptions is used for this run and is not
    # persisted to auto_rename.ordering / auto_rename.concurrency_mode / auto_rename.concurrency_workers.
    options = api.RenameOptions(
        ordering=chosen_ordering, concurrency=chosen_concurrency, workers=workers
    )

    auto_named = [f for f in bv.functions if _is_auto_named(f)]
    tag_type = create_tag_type(bv, _TAG_TYPE_NAME, icon="")
    _run_rename_batch(
        bv,
        auto_named,
        tag_type,
        "Renaming all functions (custom strategy)",
        anchor=_function_at(bv, addr),
        options=options,
    )


def _apply_var_results(bv, results, tag_type):
    successes = 0
    failures = 0
    for r in results:
        if r.new_name:
            successes += 1
            logger.info(
                f"renamed variable {r.old_name} in {r.function_name} at "
                f"{r.function_address:#x} -> {r.new_name}"
            )
            if r.reasoning:
                logger.info(f"  reason: {r.reasoning}")
            if tag_type:
                tag_item(
                    bv,
                    r.function_address,
                    _TAG_TYPE_NAME,
                    f"renamed variable {r.old_name} -> {r.new_name}",
                )
        else:
            failures += 1
            logger.warning(
                f"failed to rename variable {r.old_name} in {r.function_name}: {r.error}"
            )
    msg = f"Renamed {successes} variable(s)"
    if failures:
        msg += f", {failures} failed (see log)"
    show_message_box("Auto Rename", msg)


def _run_var_batch(bv, call):
    tag_type = create_tag_type(bv, _TAG_TYPE_NAME, icon="")

    def on_complete(results):
        bv.commit_undo_actions()
        _apply_var_results(bv, results, tag_type)

    bv.begin_undo_actions()
    call(async_run=True, on_complete=on_complete)


def _rename_variable_at_instr(bv, instr):
    func = instr.function.source_function
    if func is None:
        show_message_box("Auto Rename", "Could not resolve the containing function.")
        return
    candidates = [v for v in instr.vars if not func.is_var_user_defined(v)]
    if not candidates:
        candidates = list(instr.vars)
    if not candidates:
        show_message_box("Auto Rename", "No variable found at this location.")
        return
    var_name = candidates[0].name

    tag_type = create_tag_type(bv, _TAG_TYPE_NAME, icon="")

    def on_complete(result):
        bv.commit_undo_actions()
        _apply_var_results(bv, [result], tag_type)

    bv.begin_undo_actions()
    api.rename_variable(bv, func, var_name, async_run=True, on_complete=on_complete)


def _is_valid_hlil_var_instr(bv, instr):
    return bool(instr.vars)


def _rename_function_variables(bv, func):
    _run_var_batch(bv, lambda **kw: api.rename_variables(bv, func, **kw))


def _rename_selection_variables(bv, addr, length):
    funcs = [f for f in bv.functions if addr <= f.start < addr + length]
    if not funcs:
        show_message_box("Auto Rename", "No functions in the current selection.")
        return
    _run_var_batch(bv, lambda **kw: api.rename_all_variables(bv, restrict_to=funcs, **kw))


def _rename_all_variables(bv, addr):
    _run_var_batch(bv, lambda **kw: api.rename_all_variables(bv, **kw))


def _rename_filtered_variables(bv, addr):
    from binaryninja.interaction import get_text_line_input

    pattern = get_text_line_input(
        "Regex pattern (matches variable names):", "Auto Rename Variables (Filtered)"
    )
    if not pattern:
        return
    import re

    try:
        re.compile(pattern)
    except re.error as e:
        show_message_box("Auto Rename", f"Invalid regex: {e}")
        return
    _run_var_batch(bv, lambda **kw: api.rename_filtered_variables(bv, pattern, **kw))


def _is_valid_func(bv, func):
    return func is not None


def _is_valid_selection(bv, addr, length):
    return length > 0


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
    "auto_rename.ordering",
    "Scheduling order for bulk renaming: " + ", ".join(ORDERINGS),
    "default",
)
register_setting(
    "auto_rename.concurrency_mode",
    "Concurrency mode for bulk renaming: sequential, fixed-pool",
    "sequential",
)
register_setting(
    "auto_rename.concurrency_workers",
    "Max concurrent LLM calls when concurrency_mode is fixed-pool",
    3,
)

PluginCommand.register_for_function(
    "Auto Rename\\Auto Rename", "Rename function using AI", _rename_current, _is_valid_func
)
PluginCommand.register_for_address(
    "Auto Rename\\Auto Rename (Filtered)",
    "Rename functions matching a regex pattern",
    _rename_filtered,
)
PluginCommand.register_for_range(
    "Auto Rename\\Auto Rename (Selection)",
    "Rename selected functions using AI",
    _rename_selection,
    _is_valid_selection,
)
PluginCommand.register_for_address(
    "Auto Rename\\Auto Rename All", "Rename all auto-named functions using AI", _rename_all
)
PluginCommand.register_for_address(
    "Auto Rename\\Auto Rename All (Choose Strategy)",
    "Rename all auto-named functions using AI, picking ordering/concurrency for this run only",
    _rename_all_choose_strategy,
)

PluginCommand.register_for_high_level_il_instruction(
    "Auto Rename Variables\\Auto Rename Variable",
    "Rename the variable at this location using AI",
    _rename_variable_at_instr,
    _is_valid_hlil_var_instr,
)
PluginCommand.register_for_function(
    "Auto Rename Variables\\Auto Rename Variables (Current Function)",
    "Rename all auto-named variables in the current function using AI",
    _rename_function_variables,
    _is_valid_func,
)
PluginCommand.register_for_range(
    "Auto Rename Variables\\Auto Rename Variables (Selection)",
    "Rename auto-named variables in the selected functions using AI",
    _rename_selection_variables,
    _is_valid_selection,
)
PluginCommand.register_for_address(
    "Auto Rename Variables\\Auto Rename Variables (Filtered)",
    "Rename variables matching a regex pattern using AI",
    _rename_filtered_variables,
)
PluginCommand.register_for_address(
    "Auto Rename Variables\\Auto Rename All Variables",
    "Rename all auto-named variables in the binary using AI",
    _rename_all_variables,
)

try:
    ai_config = load_ai_config()
    provider_name = resolve_provider(ai_config).get("model", "unknown")
    logger.info(f"auto-rename loaded, provider: {provider_name}")
except Exception as e:
    logger.warning(f"auto-rename loaded, but AI config error: {e}")