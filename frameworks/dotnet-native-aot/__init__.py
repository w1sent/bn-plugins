import sys
from pathlib import Path

_plugin_dir = Path(__file__).parent.resolve()
_deps = _plugin_dir / ".deps"
if _deps.is_dir() and str(_deps) not in sys.path:
    sys.path.insert(0, str(_deps))

from binaryninja import PluginCommand
from binaryninja.interaction import show_message_box

from .core.logging import get_logger
from .core.settings import register_setting
from .core.tags import create_tag_type, tag_item

from . import api

logger = get_logger("dotnet_native_aot")

_TAG_TYPE_NAME = "NativeAOT Recovered"

register_setting(
    "dotnet_native_aot.annotate_frozen_objects",
    "Recover frozen strings/arrays/boxed values (the FROZEN_OBJECT_REGION section)",
    True,
)
register_setting(
    "dotnet_native_aot.mark_rehydration_code",
    "Leave an EOL comment on every dehydration opcode while decompressing metadata (.NET 8+)",
    False,
)


def _run_recover(bv):
    from binaryninja import Settings

    settings = Settings()
    annotate_frozen = settings.get_bool("dotnet_native_aot.annotate_frozen_objects")
    mark_rehydration_code = settings.get_bool("dotnet_native_aot.mark_rehydration_code")

    tag_type = create_tag_type(bv, _TAG_TYPE_NAME, icon="🧩")

    def on_complete(result):
        bv.commit_undo_actions()

        for warning in result.warnings:
            logger.warning(warning)

        for module in result.modules:
            tag_item(
                bv,
                module.module_header,
                _TAG_TYPE_NAME,
                f"{module.method_tables} types, {module.functions_named} methods named, "
                f"{module.strings_recovered} frozen objects",
            )

        msg = (
            f"Recovered {result.method_tables} type(s) across {len(result.modules)} module(s): "
            f"{result.functions_named} method(s) named, {result.strings_recovered} frozen object(s)"
        )
        if result.warnings:
            msg += f"\n\n{len(result.warnings)} warning(s) -- see log."
        logger.info(msg)
        show_message_box("NativeAOT Metadata Recovery", msg)

    def on_error(exc):
        bv.commit_undo_actions()
        logger.error(f"recovery failed: {exc}")
        show_message_box("NativeAOT Metadata Recovery", f"Recovery failed: {exc}")

    bv.begin_undo_actions()
    api.recover_metadata(
        bv,
        mark_rehydration_code=mark_rehydration_code,
        annotate_frozen=annotate_frozen,
        async_run=True,
        on_complete=on_complete,
        on_error=on_error,
        log=logger.info,
    )


def _is_valid(bv):
    return bv.address_size == 8


PluginCommand.register(
    "NativeAOT\\Recover Metadata",
    "Locate ReadyToRun module headers, recover the MethodTable/EEType type hierarchy, "
    "name virtual methods, and annotate frozen strings/arrays/boxed values.",
    _run_recover,
    _is_valid,
)

logger.info("dotnet-native-aot loaded")
