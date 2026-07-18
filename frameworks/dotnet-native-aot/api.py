"""Canonical, scriptable entry point for NativeAOT metadata recovery (see
ADR-0019: `api.py` is canonical, `__init__.py`'s PluginCommand wraps it).

Typical use:

    from frameworks.dotnet_native_aot import api
    result = api.recover_metadata(bv)
    print(result.method_tables, result.functions_named, result.strings_recovered)

Or asynchronously from a PluginCommand:

    api.recover_metadata(bv, async_run=True, on_complete=lambda r: ...)
"""

from dataclasses import dataclass, field

from . import codegen, frozen, rehydration, rtr
from .core.background import run_background_task
from .objectmodel import MethodTableManager, crawl


@dataclass
class ModuleResult:
    module_header: int
    method_tables: int = 0
    functions_named: int = 0
    strings_recovered: int = 0
    warnings: list = field(default_factory=list)


@dataclass
class RecoveryResult:
    modules: list = field(default_factory=list)

    @property
    def method_tables(self):
        return sum(m.method_tables for m in self.modules)

    @property
    def functions_named(self):
        return sum(m.functions_named for m in self.modules)

    @property
    def strings_recovered(self):
        return sum(m.strings_recovered for m in self.modules)

    @property
    def warnings(self):
        return [w for m in self.modules for w in m.warnings]


def _rtr_version(directory):
    # See objectmodel.py's module docstring: this threshold, and the fact
    # it looks inverted (<=8 selects the *net70* layout), is copied as-is
    # from upstream's MethodTableManager.createForDirectory.
    from .objectmodel import NET70, NET80

    return NET70 if directory.major_version <= 0x08 else NET80


def _process_module(bv, module_header, *, mark_rehydration_code, annotate_frozen, log):
    result = ModuleResult(module_header)

    directory = rtr.ReadyToRunDirectory.read_at(bv, module_header)
    version = _rtr_version(directory)
    log(f"module {module_header:#x}: RTR v{directory.major_version}.{directory.minor_version}, using {version} layout")

    dehydrated_section = directory.section_by_type(rtr.SECTION_DEHYDRATED_DATA)
    if dehydrated_section is not None:
        pointer_scan = rehydration.rehydrate(
            bv, dehydrated_section.start, dehydrated_section.end, annotate=mark_rehydration_code
        )
        log(
            f"rehydrated {pointer_scan.range_end - pointer_scan.range_start} bytes at "
            f"{pointer_scan.range_start:#x}, {len(pointer_scan.pointer_locations)} pointers"
        )
    else:
        log("no dehydrated data section -- falling back to manual pointer scan")
        pointer_scan = rehydration.scan_for_pointers(bv)
        log(f"scanned {len(pointer_scan.pointer_locations)} candidate pointers")

    manager = MethodTableManager(bv, version)
    crawl(bv, manager, pointer_scan, log=log)
    result.method_tables = len(manager.by_address)

    if manager.object_mt is None:
        result.warnings.append("could not identify System.Object; aborting this module")
        return result

    codegen.commit_all(bv, manager, log=log)
    method_stats = codegen.assign_methods(bv, manager)
    result.functions_named = method_stats["functions_named"]

    if annotate_frozen:
        result.strings_recovered = frozen.annotate_frozen_objects(
            bv, manager, directory, pointer_scan, log=log
        )

    return result


def recover_metadata(
    bv,
    *,
    mark_rehydration_code=False,
    annotate_frozen=True,
    async_run=False,
    on_complete=None,
    on_error=None,
    log=None,
):
    """Locate every NativeAOT module in `bv`, recover its type hierarchy
    (MethodTables, vtables, functions) and frozen objects (strings, SZ
    arrays, boxed values), and materialize the results as Binary Ninja
    types, data vars, symbols, and functions.

    Sync by default (returns RecoveryResult); pass async_run=True to run on
    a background thread and receive the result via on_complete instead
    (ADR-0023). `log(str)` is called with progress messages if provided.
    """

    log = log or (lambda _msg: None)

    def _run():
        module_headers = rtr.locate_modules(bv)
        if not module_headers:
            log("no ReadyToRun module headers found -- is this a NativeAOT binary?")
            return RecoveryResult()

        result = RecoveryResult()
        for header in module_headers:
            try:
                module_result = _process_module(
                    bv,
                    header,
                    mark_rehydration_code=mark_rehydration_code,
                    annotate_frozen=annotate_frozen,
                    log=log,
                )
            except Exception as exc:
                module_result = ModuleResult(header, warnings=[f"failed to process module: {exc}"])
                log(module_result.warnings[0])
            result.modules.append(module_result)

        return result

    if not async_run:
        return _run()

    return run_background_task(
        "dotnet-native-aot recover_metadata", _run, on_complete=on_complete, on_error=on_error
    )
