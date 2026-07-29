import sys
from pathlib import Path

_plugin_dir = Path(__file__).parent.resolve()
_deps = _plugin_dir / ".deps"
if _deps.is_dir() and str(_deps) not in sys.path:
    sys.path.insert(0, str(_deps))

from binaryninja import PluginCommand

from .core.evidence import record_evidence
from .core.framework_status import register_framework_indicator
from .core.logging import get_logger
from .core.settings import register_setting
from .core.tags import create_tag_type, tag_item

from . import api, rtr

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
register_setting(
    "dotnet_native_aot.auto_detect_rtr",
    "Only show NativeAOT | Recover Metadata when a ReadyToRun directory is actually "
    "detected in the binary. Turn off if detection misses a real NativeAOT binary -- "
    "the NativeAOT | Recover Metadata (Force) command is always shown regardless.",
    True,
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

    def on_error(exc):
        bv.commit_undo_actions()
        logger.error(f"recovery failed: {exc}")

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


def _record_evidence(bv, candidates):
    """Feed this detector's result into the shared evidence store (see
    docs/adr/0035-shared-evidence-store-and-context-prompt.md), so the AI
    context prompt and other tools can see it without re-running detection."""
    findings = []
    for address in candidates:
        try:
            directory = rtr.ReadyToRunDirectory.read_at(bv, address)
        except Exception:
            directory = None
        if directory is None:
            findings.append(f"ReadyToRun module detected at {address:#x}")
        else:
            findings.append(
                f"ReadyToRun module detected at {directory.address:#x} "
                f"(RTR v{directory.major_version}.{directory.minor_version}, "
                f"{len(directory.sections)} section(s))"
            )
    if not findings:
        findings = ["No ReadyToRun module detected"]
    record_evidence(bv, "dotnet_native_aot", findings)


def _has_rtr_module(bv):
    """Cached (per-bv, session-only) check for whether a ReadyToRun
    directory is actually present -- locate_modules' signature-scan
    fallback walks every non-executable data segment, so this is worth
    memoizing since _is_valid can be re-queried on every menu open."""

    cached = bv.session_data.get("dotnet_native_aot.has_rtr_module")
    if cached is not None:
        return cached

    try:
        candidates = rtr.locate_modules(bv)
    except Exception:
        candidates = []

    found = bool(candidates)
    bv.session_data["dotnet_native_aot.has_rtr_module"] = found
    _record_evidence(bv, candidates)
    return found


def _is_64bit(bv):
    return bv.address_size == 8


def _is_valid_auto(bv):
    if not _is_64bit(bv):
        return False

    from binaryninja import Settings

    if not Settings().get_bool("dotnet_native_aot.auto_detect_rtr"):
        return True
    return _has_rtr_module(bv)


PluginCommand.register(
    "NativeAOT\\Recover Metadata",
    "Locate ReadyToRun module headers, recover the MethodTable/EEType type hierarchy, "
    "name virtual methods, and annotate frozen strings/arrays/boxed values. Shown only "
    "when a ReadyToRun directory is detected (see the auto_detect_rtr setting).",
    _run_recover,
    _is_valid_auto,
)

PluginCommand.register(
    "NativeAOT\\Recover Metadata (Force)",
    "Same as NativeAOT | Recover Metadata, but always shown on 64-bit binaries -- use this "
    "if auto-detection didn't find a ReadyToRun directory but you believe this is a "
    "NativeAOT binary anyway.",
    _run_recover,
    _is_64bit,
)

register_framework_indicator("dotnet_native_aot", ".NET NativeAOT", "🧩", _has_rtr_module)

logger.info("dotnet-native-aot loaded")
