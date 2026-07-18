# flutter — Implementation TODO

Based on [blutter-binja](https://codeberg.org/w1sent/blutter-binja), transformed
into a BN-idiomatic plugin.

## Architecture
- [ ] C++ blutter tool stays as the Dart VM wrapper (required for Dart runtime access)
- [ ] Plugin drives the build: detects Dart version, checks for built tool, offers to build if missing
- [ ] Versioned tool directory: `~/.binaryninja/blutter/blutter_<version>_<os>_<arch>`
- [ ] Subprocess invocation of the C++ tool, reads `blutter.json` output
- [ ] Auto-fetch Dart SDK by default; configurable local path via `flutter.dart_sdk_path`
- [ ] Cache extracted metadata in BN's analysis database (`.bndb`)

## Detection
- [ ] Primary: analysis pass on ELF — check for Flutter markers (libapp.so symbols, Dart VM sections)
- [ ] Fallback: manual "Load Flutter Metadata" command
- [ ] Silent no-op for non-Flutter binaries
- [ ] Per ADR-0028: register the same detection check with
      `core/framework_status.register_framework_indicator("flutter", "Flutter",
      "🧩", detect_fn)` so a `🧩 Flutter` status bar indicator lights up on
      match (see `frameworks/dotnet-native-aot/__init__.py`'s
      `_has_rtr_module` for the pattern)

## BN database enrichment
- [ ] Rename functions: `func.name = dart_name`
- [ ] Rename stubs: create functions or rename data symbols at stub addresses
- [ ] Create BN `Structure` types for Dart classes (`Dart_<ClassName>`)
- [ ] Structure members for fields with inferred types
- [ ] Vtable structs: `Dart_<ClassName>_vtable` with function pointer members
- [ ] Object pool: typed `DataVariable` for known types (strings, arrays), comments for ambiguous entries
- [ ] Class inheritance: `structure.base_type` or comments
- [ ] Mixins/generics: comments (BN doesn't natively represent these)
- [ ] Tag all modified items with "Flutter" tag type

## Commands
- [ ] "Load Flutter Metadata" — manual trigger, runs extraction + enrichment

## API (`api.py`)
- [ ] `extract(bv, *, dart_sdk_path=None) -> ExtractionResult`
- [ ] `get_dart_version(bv) -> str | None`
- [ ] `get_classes(bv) -> list[DartClass]`
- [ ] `get_class(bv, name) -> DartClass | None`
- [ ] `get_functions(bv) -> list[DartFunction]`
- [ ] `get_function(bv, name) -> DartFunction | None`
- [ ] `get_object_pool(bv) -> list[PoolEntry]`
- [ ] `is_flutter_binary(bv) -> bool`
- [ ] `api.help()` — summary of all functions
- [ ] All functions fully type-hinted
- [ ] Follow BN's exception/None convention

### Types
- [ ] `DartClass(name: str, superclass: str | None, fields: list[ClassField], methods: list[str], vtable_addr: int | None)`
- [ ] `ClassField(name: str, offset: int, type: str)`
- [ ] `DartFunction(name: str, address: int, library: str, class_name: str | None)`
- [ ] `PoolEntry(address: int, kind: str, value: str)`
- [ ] `ExtractionResult(functions: int, classes: int, pool_entries: int, stubs: int)`

## Settings (BN native only)
- [ ] `flutter.dart_sdk_path` (string, default `""`) — local path or Git URL for Dart SDK; empty = auto-fetch from default GitHub URL
- [ ] `flutter.auto_extract` (bool, default `true`) — auto-run extraction on Flutter binary detection

## UI
- [ ] Progress bar with phases: detect version → build SDK → extract → apply
- [ ] Log detailed output: Dart version, build output, extraction stats, application progress
- [ ] On failure: log + notification, retry via "Load Flutter Metadata" command
- [ ] No custom views/panels unless BN-native display is insufficient (discuss first)
- [ ] No default hotkeys

## Docs
- [ ] README.md with settings, API, usage examples

## Testcases
- [ ] `testcases/general-flutter/` — standard Flutter snapshot
- [ ] `testcases/stripped-flutter/` — stripped Flutter snapshot
- [ ] Each with `build.py` and `build.py requirements`
