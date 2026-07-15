"""suggest-structs GUI test -- run via Binary Ninja's Tools > Run Script
(or paste into the built-in Python console). NOT a headless script: it
must run inside an already-open, licensed Binary Ninja GUI process, per
ADR-0009. It never uses `binaryninja.headless` / any standalone-license
API path -- `binaryninja.load()` here just opens an additional BinaryView
inside the current GUI session, the same as opening a file from the UI.

What it checks, in order (each section prints PASS/FAIL/SKIP and keeps
going -- one section failing doesn't stop the rest):
  A. Deterministic skeleton extraction (extract_skeleton) -- no LLM call,
     always runs.
  B. Trigger 1 (single mode): suggest_struct() on alloc_node's heap
     pointer. Requires a reachable AI provider (see ai-config.json).
  C. Trigger 2 (single mode): suggest_struct_from_range() on g_config.
  D. Trigger 3 (single mode): the batch candidate scan (_candidate_vars)
     runs unconditionally (no LLM); actually applying suggestions via
     suggest_all() only runs if you pass RUN_BATCH_APPLY = True below,
     since it mutates the loaded binary's types/variables.

Before running: build the test binary once --
    python testcases/struct-node/build.py
"""

import importlib.util
import sys
import traceback
from pathlib import Path

import binaryninja

# ---------------------------------------------------------------------
# Config -- edit these if you want to test against a different provider,
# skip the (mutating) batch-apply section, or point at a different binary.
# ---------------------------------------------------------------------
FORCE_MODE = "single"   # "single" or "multi" -- single is faster/cheaper for a smoke test
RUN_BATCH_APPLY = False  # True runs suggest_all() for real (mutates the loaded bv)

_HERE = Path(__file__).resolve()
_PLUGIN_DIR = _HERE.parent.parent               # ai/suggest-structs
_REPO_ROOT = _PLUGIN_DIR.parent.parent           # repo root
_TESTCASE_BIN = _REPO_ROOT / "testcases" / "struct-node" / "node.bin"

_PASS, _FAIL, _SKIP = [], [], []


def _report(status, name, detail=""):
    bucket = {"PASS": _PASS, "FAIL": _FAIL, "SKIP": _SKIP}[status]
    bucket.append(name)
    line = f"[{status}] {name}"
    if detail:
        line += f" -- {detail}"
    print(line)


# ---------------------------------------------------------------------
# Bootstrap: import suggest-structs' api.py as a real package submodule
# (so its `from .core...` relative imports resolve) without executing
# __init__.py -- that would re-register PluginCommands/Settings a second
# time if the plugin is also installed normally. `core/` lives at the repo
# root in this dev checkout (see scripts/install.py, which copies/symlinks
# it into the installed plugin dir) rather than inside ai/suggest-structs/,
# so the synthetic package's search path includes both locations.
# ---------------------------------------------------------------------

def _load_plugin_api():
    pkg_name = "_suggest_structs_test_harness"
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
    if not _TESTCASE_BIN.exists():
        print(f"Test binary not found at {_TESTCASE_BIN}.")
        print("Build it first: python testcases/struct-node/build.py")
        return

    api = _load_plugin_api()

    print(f"Loading {_TESTCASE_BIN} ...")
    bv = binaryninja.load(str(_TESTCASE_BIN))
    bv.update_analysis_and_wait()
    print(f"Loaded, {len(list(bv.functions))} functions analyzed.\n")

    # -- A. deterministic skeleton extraction (no LLM) ------------------
    print("-- A. skeleton extraction (extract_skeleton) --")
    try:
        alloc_funcs = [f for f in bv.functions if f.name == "alloc_node"]
        if not alloc_funcs:
            _report("FAIL", "A: find alloc_node", "function not found -- did the binary build correctly?")
            func, target_var = None, None
        else:
            func = alloc_funcs[0]
            candidates = [v for v in func.hlil.vars if "*" in str(v.type)] if func.hlil else []
            best = max(candidates, key=lambda v: len(api.extract_skeleton(bv, func, v)), default=None)
            if best is None:
                _report("FAIL", "A: find candidate pointer var in alloc_node", "no pointer-typed HLIL var found")
                target_var = None
            else:
                skeleton = api.extract_skeleton(bv, func, best)
                offsets = sorted(f.offset for f in skeleton)
                print(f"  variable: {best.name}, offsets found: {[hex(o) for o in offsets]}")
                # We wrote *(int*)(p+0), *(int*)(p+4), memcpy(p+8, ...), *(void**)(p+24).
                # memcpy doesn't produce a DEREF_FIELD/ARRAY_INDEX BN can see as an
                # offset access, so we only expect 0x0, 0x4, 0x18 to reliably show up
                # -- treat this as informational rather than a strict assertion, since
                # decompiler output varies by BN version/optimization.
                expected = {0x0, 0x4, 0x18}
                found = expected & set(offsets)
                if found:
                    _report("PASS", "A: skeleton extraction", f"found {len(found)}/{len(expected)} expected offsets")
                else:
                    _report("FAIL", "A: skeleton extraction", f"expected some of {sorted(expected)}, got {offsets}")
                target_var = best
    except Exception as e:
        _report("FAIL", "A: skeleton extraction", f"{e}\n{traceback.format_exc()}")
        func, target_var = None, None

    # -- B. trigger 1: suggest_struct (single mode) ----------------------
    print("\n-- B. trigger 1: suggest_struct (single mode) --")
    if func is None or target_var is None:
        _report("SKIP", "B: suggest_struct", "no target variable from section A")
    else:
        try:
            options = api.StructOptions(mode=FORCE_MODE)
            result = api.suggest_struct(bv, func.start, var_name=target_var.name, options=options)
            if result.error:
                _report("FAIL", "B: suggest_struct", result.error)
            elif not result.definition:
                _report("FAIL", "B: suggest_struct", "no definition returned")
            else:
                print(f"  proposed definition:\n{result.definition}\n")
                parsed = bv.parse_types_from_string(result.definition)
                if parsed.types:
                    _report("PASS", "B: suggest_struct", f"parsed {len(parsed.types)} type(s)")
                else:
                    _report("FAIL", "B: suggest_struct", "LLM output didn't parse into any struct")
        except Exception as e:
            _report("FAIL", "B: suggest_struct", f"{e} -- is a provider configured in ai-config.json?")

    # -- C. trigger 2: suggest_struct_from_range (single mode) -----------
    print("\n-- C. trigger 2: suggest_struct_from_range (single mode) --")
    try:
        g_config_syms = bv.get_symbols_by_name("g_config")
        if not g_config_syms:
            _report("FAIL", "C: find g_config", "symbol not found")
        else:
            addr = g_config_syms[0].address
            options = api.StructOptions(mode=FORCE_MODE)
            result = api.suggest_struct_from_range(bv, addr, 16, options=options)
            if result.error:
                _report("FAIL", "C: suggest_struct_from_range", result.error)
            elif not result.definition:
                _report("FAIL", "C: suggest_struct_from_range", "no definition returned")
            else:
                print(f"  proposed definition:\n{result.definition}\n")
                _report("PASS", "C: suggest_struct_from_range", "")
    except Exception as e:
        _report("FAIL", "C: suggest_struct_from_range", f"{e} -- is a provider configured in ai-config.json?")

    # -- D. trigger 3: batch candidate scan (no LLM) + optional apply ---
    print("\n-- D. trigger 3: batch candidate scan (_candidate_vars) --")
    try:
        threshold, _max_steps, _max_structs = api._resolve_bn_settings(bv, api.StructOptions())
        candidates = api._candidate_vars(bv, threshold)
        names = [(hex(a), v) for a, v in candidates]
        print(f"  candidates found: {names}")
        has_scratch_global = any(v is None for _a, v in candidates)
        has_alloc_var = any(v is not None for _a, v in candidates)
        if has_scratch_global and has_alloc_var:
            _report("PASS", "D: candidate scan", "found both a global (data_<addr>) and a variable candidate")
        else:
            _report(
                "FAIL", "D: candidate scan",
                f"expected at least one global and one variable candidate, got: {names}",
            )
    except Exception as e:
        _report("FAIL", "D: candidate scan", f"{e}\n{traceback.format_exc()}")

    if RUN_BATCH_APPLY:
        print("\n-- D2. trigger 3: suggest_all (mutates bv) --")
        try:
            options = api.StructOptions(mode=FORCE_MODE)
            results = api.suggest_all(bv, options=options)
            applied = sum(1 for r in results if r.applied)
            failed = sum(1 for r in results if r.error)
            print(f"  {len(results)} candidate(s): {applied} applied, {failed} failed")
            for r in results:
                tag = "applied" if r.applied else ("error" if r.error else "unapplied")
                print(f"    [{tag}] {r.address:#x} {r.var_name or ''} -> {r.struct_name or r.error}")
            if applied > 0:
                _report("PASS", "D2: suggest_all", f"{applied} applied")
            else:
                _report("FAIL", "D2: suggest_all", "nothing applied")
        except Exception as e:
            _report("FAIL", "D2: suggest_all", f"{e}\n{traceback.format_exc()}")
    else:
        _report("SKIP", "D2: suggest_all", "RUN_BATCH_APPLY is False")

    print(f"\n{len(_PASS)} passed, {len(_FAIL)} failed, {len(_SKIP)} skipped.")


main()
