"""suggest-structs GUI test -- run via Binary Ninja's Tools > Run Script
(or paste into the built-in Python console). NOT a headless script: it
must run inside an already-open, licensed Binary Ninja GUI process, per
ADR-0009. It never uses `binaryninja.headless` / any standalone-license
API path -- `binaryninja.load()` here just opens an additional BinaryView
inside the current GUI session, the same as opening a file from the UI.

What it checks, in order (each section prints PASS/FAIL/SKIP and keeps
going -- one section failing doesn't stop the rest). LLM calls only happen
in B and C; everything else is deterministic (no provider needed):

  A. Skeleton extraction (extract_skeleton) on alloc_node's heap pointer.
  B. Trigger 1 (suggest_struct) on that same pointer -- LLM call.
  C. Trigger 2 (suggest_struct_from_range) on the g_config global -- LLM
     call. g_config is NOT inside any function, so this also covers the
     "no containing function" path (see api._build_range_context).
  D. Batch candidate scan (_candidate_vars) -- confirms both a named
     variable and a data_<addr>-named (symbol-stripped) global are found.
  E. Applies B's suggestion for real via api.apply_definition (the same
     call __init__.py's preview-accept path makes) and checks the
     variable's type and a tag actually landed.
  F. Existing-type reuse/dedup guard: defines a type once via
     api._apply_definition, then again with the same name, and checks it
     wasn't redefined -- this is the deterministic guard described in
     README.md's "existing-type reuse", independent of whether the LLM
     itself chooses to reuse a type.
  G. confidence_threshold's effect on the batch candidate scan: a very low
     threshold should exclude nearly everything, a very high one should
     include at least as much as the default.
  H. Applies a hand-written struct directly to a global via the private
     `_apply_definition`'s `data_addr` path (bypassing the LLM) and checks
     it landed as a value type on that data variable, distinct from E's
     pointer-to-var case.
  H2. Same as H but through the *public* api.apply_definition -- the actual
      call __init__.py's range-selection preview-accept path makes. Guards
      against that wrapper crashing on func=None / dropping data_addr.
  I. suggest_all() (the actual batch command's underlying call) -- runs
     unconditionally by default now that A-H are known-good (see
     RUN_BATCH_APPLY below to opt back out; it mutates the loaded bv,
     which is an in-memory testcase binary, not anything of yours).

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
RUN_BATCH_APPLY = True  # False skips section I (suggest_all actually applying)

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

    tag_type = bv.create_tag_type("AI Struct (test)", "")

    # -- A. deterministic skeleton extraction (no LLM) ------------------
    print("-- A. skeleton extraction (extract_skeleton) --")
    func, target_var = None, None
    try:
        alloc_funcs = [f for f in bv.functions if f.name == "alloc_node"]
        if not alloc_funcs:
            _report("FAIL", "A: find alloc_node", "function not found -- did the binary build correctly?")
        else:
            func = alloc_funcs[0]
            candidates = [v for v in func.hlil.vars if "*" in str(v.type)] if func.hlil else []
            print(f"  pointer-typed HLIL vars in alloc_node: {[(v.name, str(v.type)) for v in candidates]}")
            for v in candidates:
                sk = api.extract_skeleton(bv, func, v)
                print(f"    {v.name}: offsets {[hex(f.offset) for f in sk]}")

            best = max(candidates, key=lambda v: len(api.extract_skeleton(bv, func, v)), default=None)
            if best is None:
                _report("FAIL", "A: find candidate pointer var in alloc_node", "no pointer-typed HLIL var found")
            else:
                skeleton = api.extract_skeleton(bv, func, best)
                offsets = sorted(f.offset for f in skeleton)
                print(f"  variable: {best.name}, offsets found: {[hex(o) for o in offsets]}")
                # We wrote *(int*)(p+0), *(int*)(p+4), memcpy(p+8, ...), *(void**)(p+24).
                # memcpy doesn't produce a matchable offset access, so we only expect
                # 0x0, 0x4, 0x18 to reliably show up.
                expected = {0x0, 0x4, 0x18}
                found = expected & set(offsets)
                if found:
                    _report("PASS", "A: skeleton extraction", f"found {len(found)}/{len(expected)} expected offsets")
                else:
                    _report("FAIL", "A: skeleton extraction", f"expected some of {sorted(expected)}, got {offsets}")
                target_var = best
    except Exception as e:
        _report("FAIL", "A: skeleton extraction", f"{e}\n{traceback.format_exc()}")

    # -- B. trigger 1: suggest_struct (single mode) ----------------------
    print("\n-- B. trigger 1: suggest_struct (single mode) --")
    b_result = None
    if func is None or target_var is None:
        _report("SKIP", "B: suggest_struct", "no target variable from section A")
    else:
        try:
            options = api.StructOptions(mode=FORCE_MODE)
            b_result = api.suggest_struct(bv, func.start, var_name=target_var.name, options=options)
            if b_result.error:
                _report("FAIL", "B: suggest_struct", b_result.error)
                b_result = None
            elif not b_result.definition:
                _report("FAIL", "B: suggest_struct", "no definition returned")
                b_result = None
            else:
                print(f"  proposed definition:\n{b_result.definition}\n")
                parsed = bv.parse_types_from_string(b_result.definition)
                if parsed.types:
                    _report("PASS", "B: suggest_struct", f"parsed {len(parsed.types)} type(s)")
                else:
                    _report("FAIL", "B: suggest_struct", "LLM output didn't parse into any struct")
                    b_result = None
        except Exception as e:
            _report("FAIL", "B: suggest_struct", f"{e} -- is a provider configured in ai-config.json?")

    # -- C. trigger 2: suggest_struct_from_range (single mode) -----------
    print("\n-- C. trigger 2: suggest_struct_from_range (single mode) --")
    c_result, g_config_addr = None, None
    try:
        g_config_syms = bv.get_symbols_by_name("g_config")
        if not g_config_syms:
            _report("FAIL", "C: find g_config", "symbol not found")
        else:
            g_config_addr = g_config_syms[0].address
            options = api.StructOptions(mode=FORCE_MODE)
            c_result = api.suggest_struct_from_range(bv, g_config_addr, 16, options=options)
            if c_result.error:
                _report("FAIL", "C: suggest_struct_from_range", c_result.error)
                c_result = None
            elif not c_result.definition:
                _report("FAIL", "C: suggest_struct_from_range", "no definition returned")
                c_result = None
            else:
                print(f"  proposed definition:\n{c_result.definition}\n")
                _report("PASS", "C: suggest_struct_from_range", "")
    except Exception as e:
        _report("FAIL", "C: suggest_struct_from_range", f"{e} -- is a provider configured in ai-config.json?")

    # -- D. trigger 3: batch candidate scan (no LLM) ---------------------
    print("\n-- D. trigger 3: batch candidate scan (_candidate_vars) --")
    try:
        threshold, _max_steps, _max_structs = api._resolve_bn_settings(bv, api.StructOptions())
        candidates = api._candidate_vars(bv, threshold)
        names = [(hex(a), v) for a, v in candidates]
        print(f"  candidates found: {names}")
        has_global = any(v is None for _a, v in candidates)
        has_var = any(v is not None for _a, v in candidates)
        if has_global and has_var:
            _report("PASS", "D: candidate scan", "found both a global (data_<addr>) and a variable candidate")
        else:
            _report(
                "FAIL", "D: candidate scan",
                f"expected at least one global and one variable candidate, got: {names}",
            )
    except Exception as e:
        _report("FAIL", "D: candidate scan", f"{e}\n{traceback.format_exc()}")

    # -- E. apply_definition end-to-end (the preview-accept code path) --
    print("\n-- E. apply_definition (preview-accept path) --")
    if b_result is None or func is None or target_var is None:
        _report("SKIP", "E: apply_definition", "no unapplied definition from section B")
    else:
        try:
            applied = api.apply_definition(bv, func, target_var, b_result.definition, tag_type)
            if applied.error:
                _report("FAIL", "E: apply_definition", applied.error)
            else:
                # create_user_var() queues a re-analysis rather than updating
                # func.hlil.vars synchronously -- wait for it, and re-fetch
                # `func` too, before reading the variable's type back.
                bv.update_analysis_and_wait()
                fresh_funcs = bv.get_functions_containing(func.start)
                fresh_func = fresh_funcs[0] if fresh_funcs else func
                refreshed = api._hlil_var_for(fresh_func, target_var.name)
                new_type = str(refreshed.type) if refreshed is not None else "?"
                tags = bv.get_tags_at(func.start)
                print(f"  {target_var.name} type is now: {new_type}")
                print(f"  tags at {func.start:#x}: {[(t.type.name, t.data) for t in tags]}")
                is_struct_ptr = "*" in new_type and applied.struct_name and str(applied.struct_name) in new_type
                has_tag = any(t.type.name == tag_type.name for t in tags)
                if is_struct_ptr and has_tag:
                    _report("PASS", "E: apply_definition", f"{target_var.name} -> {new_type}, tagged")
                else:
                    _report(
                        "FAIL", "E: apply_definition",
                        f"type={new_type!r} struct_name={applied.struct_name!r} tagged={has_tag}",
                    )
        except Exception as e:
            _report("FAIL", "E: apply_definition", f"{e}\n{traceback.format_exc()}")

    # -- F. existing-type reuse/dedup guard (no LLM) ---------------------
    print("\n-- F. existing-type reuse/dedup guard --")
    try:
        dedup_name = "SuggestStructsTestDedup"
        before = sum(1 for n in bv.type_names if str(n) == dedup_name)
        name1, applied1, err1 = api._apply_definition(
            bv, None, None, f"struct {dedup_name} {{ int32_t a; }};", None,
        )
        mid = sum(1 for n in bv.type_names if str(n) == dedup_name)
        name2, applied2, err2 = api._apply_definition(
            bv, None, None, f"struct {dedup_name} {{ int32_t a; }};", None,
        )
        after = sum(1 for n in bv.type_names if str(n) == dedup_name)
        print(f"  {dedup_name} count: before={before} after 1st define={mid} after 2nd define={after}")
        if err1 or err2:
            _report("FAIL", "F: dedup guard", f"err1={err1} err2={err2}")
        elif before == 0 and mid == 1 and after == 1:
            _report("PASS", "F: dedup guard", "second definition reused instead of duplicating")
        else:
            _report("FAIL", "F: dedup guard", f"expected 0/1/1, got {before}/{mid}/{after}")
    except Exception as e:
        _report("FAIL", "F: dedup guard", f"{e}\n{traceback.format_exc()}")

    # -- G. confidence_threshold's effect on the candidate scan ----------
    print("\n-- G. confidence_threshold effect on batch scan --")
    try:
        low = api._candidate_vars(bv, 0)
        default_threshold, _, _ = api._resolve_bn_settings(bv, api.StructOptions())
        default = api._candidate_vars(bv, default_threshold)
        high = api._candidate_vars(bv, 300)
        print(f"  candidate counts -- threshold=0: {len(low)}, default({default_threshold}): {len(default)}, threshold=300: {len(high)}")
        if len(low) <= len(default) <= len(high):
            _report("PASS", "G: confidence_threshold", f"{len(low)} <= {len(default)} <= {len(high)}")
        else:
            _report("FAIL", "G: confidence_threshold", f"not monotonic: {len(low)}, {len(default)}, {len(high)}")
    except Exception as e:
        _report("FAIL", "G: confidence_threshold", f"{e}\n{traceback.format_exc()}")

    # -- H. apply to a global via the data_addr path (no LLM) ------------
    print("\n-- H. apply_definition on a global (data_addr path) --")
    if g_config_addr is None:
        _report("SKIP", "H: data_addr apply", "g_config not found (section C)")
    else:
        try:
            struct_name, applied, error = api._apply_definition(
                bv, None, None,
                "struct HandWrittenConfig { uint32_t magic; uint16_t version; uint16_t flags; char tag[8]; };",
                tag_type, data_addr=g_config_addr,
            )
            data_var = bv.get_data_var_at(g_config_addr)
            new_type = str(data_var.type) if data_var is not None else "?"
            tags = bv.get_tags_at(g_config_addr)
            has_tag = any(t.type.name == tag_type.name for t in tags)
            print(f"  g_config type is now: {new_type}, tagged={has_tag}")
            if error:
                _report("FAIL", "H: data_addr apply", error)
            elif "HandWrittenConfig" in new_type and has_tag:
                _report("PASS", "H: data_addr apply", f"g_config -> {new_type}, tagged")
            else:
                _report("FAIL", "H: data_addr apply", f"type={new_type!r} tagged={has_tag}")
        except Exception as e:
            _report("FAIL", "H: data_addr apply", f"{e}\n{traceback.format_exc()}")

    # -- H2. api.apply_definition (public wrapper) via data_addr ---------
    # Regression guard: the range-selection trigger (__init__.py's
    # _suggest_selection -> _show_preview_and_apply) calls the *public*
    # api.apply_definition, not api._apply_definition -- H above only
    # exercises the private helper directly, which didn't catch that the
    # public wrapper used to hard-crash on func.start when func is None
    # (selecting a memory region outside any function) and never threaded
    # data_addr through at all.
    print("\n-- H2. apply_definition (public wrapper, data_addr path) --")
    if c_result is None or g_config_addr is None:
        _report("SKIP", "H2: apply_definition data_addr", "no unapplied definition from section C")
    else:
        try:
            applied = api.apply_definition(
                bv, None, None, c_result.definition, tag_type, data_addr=g_config_addr,
            )
            if applied.error:
                _report("FAIL", "H2: apply_definition data_addr", applied.error)
            else:
                data_var = bv.get_data_var_at(g_config_addr)
                new_type = str(data_var.type) if data_var is not None else "?"
                tags = bv.get_tags_at(g_config_addr)
                has_tag = any(t.type.name == tag_type.name for t in tags)
                print(f"  g_config type is now: {new_type}, tagged={has_tag}")
                is_struct = applied.struct_name and str(applied.struct_name) in new_type
                if is_struct and has_tag and applied.address == g_config_addr:
                    _report("PASS", "H2: apply_definition data_addr", f"g_config -> {new_type}, tagged")
                else:
                    _report(
                        "FAIL", "H2: apply_definition data_addr",
                        f"type={new_type!r} struct_name={applied.struct_name!r} "
                        f"tagged={has_tag} address={applied.address:#x}",
                    )
        except Exception as e:
            _report("FAIL", "H2: apply_definition data_addr", f"{e}\n{traceback.format_exc()}")

    # -- I. suggest_all (the real batch command's call), mutates bv ------
    print("\n-- I. suggest_all (batch apply) --")
    if not RUN_BATCH_APPLY:
        _report("SKIP", "I: suggest_all", "RUN_BATCH_APPLY is False")
    else:
        try:
            options = api.StructOptions(mode=FORCE_MODE)
            results = api.suggest_all(bv, options=options, tag_type_name=tag_type)
            applied = sum(1 for r in results if r.applied)
            failed = sum(1 for r in results if r.error)
            print(f"  {len(results)} candidate(s): {applied} applied, {failed} failed")
            for r in results:
                tag = "applied" if r.applied else ("error" if r.error else "unapplied")
                print(f"    [{tag}] {r.address:#x} {r.var_name or ''} -> {r.struct_name or r.error}")
            if len(results) == 0:
                _report(
                    "PASS", "I: suggest_all",
                    "no remaining candidates -- expected, E/F/H already typed alloc_node's var and g_config",
                )
            elif applied > 0:
                _report("PASS", "I: suggest_all", f"{applied}/{len(results)} applied")
            else:
                _report("FAIL", "I: suggest_all", f"{len(results)} candidate(s), none applied")
        except Exception as e:
            _report("FAIL", "I: suggest_all", f"{e}\n{traceback.format_exc()}")

    print(f"\n{len(_PASS)} passed, {len(_FAIL)} failed, {len(_SKIP)} skipped.")


main()
