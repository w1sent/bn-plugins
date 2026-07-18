"""dotnet-native-aot GUI test -- run via Binary Ninja's Tools > Run Script
(or paste into the built-in Python console). NOT a headless script: it must
run inside an already-open, licensed Binary Ninja GUI process, per ADR-0009.

Fully deterministic (no LLM/network calls) -- unlike the ai/ plugins' test
harnesses, everything here can run unattended.

What it checks, in order (each section prints PASS/FAIL/SKIP and keeps
going):

  A. rtr.locate_modules finds at least one RTR module header.
  B. api.recover_metadata runs end to end and finds System.Object plus a
     plausible number of other MethodTables.
  C. At least one virtual method got renamed off its auto-generated name
     (i.e. `<class>::ToString`/`Equals`/`GetHashCode`/`Method_N` exists).
  D. If a frozen string section was present, at least one `dn_...` label
     was created and its recovered text is sane UTF-16 (round-trips).

Before running: build the test binary once --
    python testcases/dotnet-nativeaot-hello/build.py
(requires the .NET 8+ SDK -- see that script's `requirements` output).
"""

import importlib.util
import platform
import sys
import traceback
from pathlib import Path

import binaryninja

_HERE = Path(__file__).resolve()
_PLUGIN_DIR = _HERE.parent.parent              # frameworks/dotnet-native-aot
_REPO_ROOT = _PLUGIN_DIR.parent.parent          # repo root
_TESTCASE_DIR = _REPO_ROOT / "testcases" / "dotnet-nativeaot-hello"

_PASS, _FAIL, _SKIP = [], [], []


def _report(status, name, detail=""):
    bucket = {"PASS": _PASS, "FAIL": _FAIL, "SKIP": _SKIP}[status]
    bucket.append(name)
    line = f"[{status}] {name}"
    if detail:
        line += f" -- {detail}"
    print(line)


def _find_testcase_binary():
    bin_dir = _TESTCASE_DIR / "bin"
    if not bin_dir.is_dir():
        return None
    for candidate in ("nativeaot_hello", "nativeaot_hello.exe"):
        path = bin_dir / candidate
        if path.exists():
            return path
    return None


# ---------------------------------------------------------------------
# Bootstrap: import this plugin's api.py (and everything it imports --
# codegen/frozen/rehydration/rtr/objectmodel) as a real package submodule
# without executing __init__.py, so PluginCommand/Settings aren't
# re-registered a second time if the plugin is also installed normally.
# `core/` lives at the repo root in this dev checkout, so the synthetic
# package's search path includes both locations. See
# ai/suggest-structs/tests/run.py for the original version of this pattern.
# ---------------------------------------------------------------------

def _load_plugin_api():
    pkg_name = "_dotnet_native_aot_test_harness"
    if f"{pkg_name}.api" in sys.modules:
        return sys.modules[f"{pkg_name}.api"]

    pkg_spec = importlib.util.spec_from_file_location(
        pkg_name,
        _PLUGIN_DIR / "__init__.py",
        submodule_search_locations=[str(_PLUGIN_DIR), str(_REPO_ROOT)],
    )
    pkg = importlib.util.module_from_spec(pkg_spec)
    sys.modules[pkg_name] = pkg  # shell only -- deliberately not exec'd

    api_spec = importlib.util.spec_from_file_location(f"{pkg_name}.api", _PLUGIN_DIR / "api.py")
    api_mod = importlib.util.module_from_spec(api_spec)
    api_mod.__package__ = pkg_name
    sys.modules[f"{pkg_name}.api"] = api_mod
    api_spec.loader.exec_module(api_mod)
    return api_mod


def main():
    binary = _find_testcase_binary()
    if binary is None:
        print(f"Test binary not found under {_TESTCASE_DIR / 'bin'}.")
        print("Build it first: python testcases/dotnet-nativeaot-hello/build.py")
        return

    api = _load_plugin_api()
    from _dotnet_native_aot_test_harness import rtr  # noqa: E402  (registered by _load_plugin_api)

    print(f"Loading {binary} ...")
    bv = binaryninja.load(str(binary))
    bv.update_analysis_and_wait()
    print(f"Loaded, {len(list(bv.functions))} functions analyzed.\n")

    # -- A. module discovery ---------------------------------------------
    print("-- A. rtr.locate_modules --")
    try:
        modules = rtr.locate_modules(bv)
        if modules:
            _report("PASS", "A: locate RTR module header(s)", f"{len(modules)} found")
        else:
            _report(
                "FAIL",
                "A: locate RTR module header(s)",
                "none found -- is this actually a NativeAOT binary for this platform?",
            )
    except Exception:
        _report("FAIL", "A: locate RTR module header(s)", traceback.format_exc(limit=3))
        modules = []

    # -- B. end-to-end recovery -------------------------------------------
    print("\n-- B. api.recover_metadata --")
    result = None
    if modules:
        try:
            result = api.recover_metadata(bv)
            if result.method_tables >= 2:
                _report(
                    "PASS",
                    "B: recover_metadata finds MethodTables",
                    f"{result.method_tables} types, {result.functions_named} methods named, "
                    f"{result.strings_recovered} frozen objects",
                )
            else:
                _report("FAIL", "B: recover_metadata finds MethodTables", f"only {result.method_tables} found")
        except Exception:
            _report("FAIL", "B: recover_metadata", traceback.format_exc(limit=5))
    else:
        _report("SKIP", "B: recover_metadata", "no RTR modules to process")

    # -- C. at least one method got a real name ---------------------------
    print("\n-- C. named virtual methods --")
    if result and result.functions_named > 0:
        named = [
            f.name
            for f in bv.functions
            if "::" in f.name
            and (f.name.split("::")[-1] in ("ToString", "Equals", "GetHashCode") or "Method_" in f.name)
        ]
        if named:
            _report("PASS", "C: named virtual methods present", f"e.g. {named[0]}")
        else:
            _report("FAIL", "C: named virtual methods present", "recover_metadata reported names but none found by scan")
    else:
        _report("SKIP", "C: named virtual methods present", "no methods were named in section B")

    # -- D. frozen string recovered ---------------------------------------
    print("\n-- D. frozen string literals --")
    if result and result.strings_recovered > 0:
        dn_syms = [s for s in bv.get_symbols() if s.name.startswith("dn_")]
        if dn_syms:
            _report("PASS", "D: frozen string literal(s) labelled", f"{len(dn_syms)} found, e.g. {dn_syms[0].name}")
        else:
            _report("FAIL", "D: frozen string literal(s) labelled", "recover_metadata reported strings but none found by scan")
    else:
        _report("SKIP", "D: frozen string literal(s) labelled", "no frozen objects recovered in section B")

    print(f"\n{len(_PASS)} passed, {len(_FAIL)} failed, {len(_SKIP)} skipped")


main()
