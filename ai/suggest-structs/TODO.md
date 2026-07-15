# suggest-structs — Implementation TODO

Design settled via grilling session; see ADR-0027 for the preview-mechanism
deviation from ADR-0024.

**Status:** implemented (`api.py`, `agent.py`, `__init__.py`, `plugin.json`,
`prompts/`, `requirements.txt`, `README.md`). Unverified against a live
Binary Ninja instance — no `binaryninja` package is importable in this dev
environment, only reference source/docs at `$BN_SRC/`.
No automated tests were added: unlike auto-rename's `ordering.py`, none of
this plugin's logic is cleanly separable from `binaryninja` HLIL/BinaryView
objects into a duck-typeable pure-Python module, so there's nothing to test
without first-run verification in real BN or inventing test seams the task
didn't ask for.

## Triggers
- [x] Trigger 1 (variable): pointer-typed HLIL variable at cursor -> deterministic
      access-pattern extraction (offsets/sizes/gaps) as an advisory skeleton, handed
      to the LLM as context alongside surrounding disassembly/string/data refs and
      existing type names. Skeleton is advisory, not a hard constraint on the LLM.
- [x] Trigger 2 (range): selection over a byte range -> seed a struct sized to the
      range, then run trigger 1's LLM refinement step on the seed.
- [x] Trigger 3 (batch sweep): all candidate pointer-typed local/param HLIL vars
      across all functions, plus global `data_<addr>`-named vars, filtered by
      `suggest_structs.confidence_threshold` (skip vars at/above threshold -- default
      255, i.e. only vars BN itself doesn't already consider user-set). Globals run
      through trigger 2, sized to the data var's own length.

## Commands
- [x] "Suggest Struct" (`register_for_function`-style, `is_valid` checks pointer var
      at cursor) -> trigger 1
- [x] "Suggest Struct (Selection)" (`register_for_range`, `is_valid` checks length>0)
      -> trigger 2
- [x] "Suggest Struct (Batch)" (`register_for_address`) -> trigger 3, applies
      directly without preview, honors configured `mode` (single or multi) per
      candidate regardless of cost

## LLM output & type handling
- [x] LLM output is a full C struct definition (free text), not JSON -- symmetric
      with the preview surface, round-tripped through `bv.parse_type_string`
- [x] Existing-type reuse is LLM-driven: existing user-defined type names/defs are
      given as context; LLM decides whether to reference an existing struct or
      define a new one. Deterministic guard: if the emitted name already exists in
      `bv.types`, skip redefinition and just reference it.

## Modes
- [x] `single` mode: one-shot langchain call, fixed context bundle (skeleton +
      function HLIL + string/data refs + existing type names), one LLM call
- [x] `multi` mode: deepagents agent (built locally in `ai/suggest-structs/agent.py`,
      not shared `core/` -- first deepagents consumer in the repo) with tools:
      - `get_variable_context(address, var_name)` -- skeleton + context for any var,
        callable recursively for nested/related structs
      - `lookup_type(name)` -- exact C definition of an existing user-defined type
      - `list_type_names(prefix=None)` -- cheap enumeration
      - `submit_struct(name, c_definition)` -- callable multiple times (incremental)
      - `undo_struct(name)` -- retract a struct submitted earlier this session
      - `apply_struct(address, var_name, struct_name)` -- apply a struct to a
        variable directly (live BV mutation during the session)
      - `confirm_edits()` -- terminates the session; required for success (a session
        that ends without it is a failure result, not a partial result)
- [x] Multi mode wraps the whole session (`apply_struct`/`submit_struct` calls) in
      one `bv.begin_undo_actions()`/`commit_undo_actions()` pair, committed only on
      `confirm_edits()`. Cancel mid-session = full rollback (undo actions abandoned,
      never committed) -- no partial commit.

## Preview (single-item, non-batch, `single` mode only)
- [x] Background thread runs the LLM call (progress via `BackgroundTask`, same
      pattern as auto-rename); `on_complete` schedules a popup on the main thread
      (`execute_on_main_thread`)
- [x] Popup: editable free-text C syntax (`interaction.MultilineTextField` /
      `get_form_input`), pre-filled with the LLM's proposed struct
- [x] Accept -> `bv.parse_type_string` -> `bv.define_user_type` +
      `Function.create_user_var`; Cancel -> nothing applied
- [x] `multi` mode has no separate preview step for the single-item command -- its
      own tool loop (`submit_struct`/`undo_struct`/`confirm_edits`) is the
      interactive/correctable surface instead (see ADR-0027, Q10 in design session)

## Batch behavior
- [x] No preview, applies directly per candidate as processed
- [x] Single undo action wrapping the entire batch (`begin_undo_actions` /
      `commit_undo_actions`), same shape as auto-rename
- [x] Cancel = stop submitting further candidates, keep what's already applied (same
      semantics as auto-rename's batch cancel) -- not a full rollback (that's
      multi-mode single-item only, see above)
- [x] Progress bar + per-item log + completion notification (non-blocking)
- [x] Cancel via progress bar button

## Tagging & results
- [x] Tag "AI Struct" on the containing function's address at each site a struct is
      applied to a variable (including nested applications from multi mode) -- not
      on the bare type definition, which has no address
- [x] No confidence scores displayed (this is about the LLM's own self-reported
      confidence, unrelated to the BN `Type.confidence` filter above)
- [x] Log message on load: provider, model

## API (`api.py`)
- [x] `suggest_struct(bv, addr, *, provider=None, mode=None, options=None) -> StructResult`
- [x] `suggest_struct_from_range(bv, start, length, *, provider=None, mode=None, options=None) -> StructResult`
      (deviation from original TODO -- trigger 2 needs a distinct signature from a
      single address; implemented as range-seed + shared refinement helper with
      `suggest_struct`, not duplicated logic)
- [x] `suggest_structs(bv, addrs, *, provider=None, mode=None, options=None) -> list[StructResult]`
- [x] `suggest_all(bv, *, provider=None, mode=None, options=None) -> list[StructResult]`
- [x] `api.help()` -- summary of all functions
- [x] `async_run=True` returns Future-like object (`_AsyncResult`, same shape as
      auto-rename's)
- [x] All functions fully type-hinted
- [x] Follow BN's exception/None convention

## Settings (BN native)
- [x] `suggest_structs.provider` (string, default `""` -> use ai-config default)
- [x] `suggest_structs.mode` (enum: `"single"` / `"multi"`, default `"multi"`)
- [x] `suggest_structs.config_path` (string, default `~/.binaryninja/suggest-structs.json`)
- [x] `suggest_structs.confidence_threshold` (int, default 255) -- variables at or
      above this `Type.confidence` are skipped as "already typed" by batch sweep
- [x] `suggest_structs.agent_max_steps` (int) -- multi-mode tool-call budget per session
- [x] `suggest_structs.agent_max_structs_per_session` (int) -- cap on
      `submit_struct` calls per multi-mode session

## UI
- [x] Register on all surfaces (context menu, command palette, toolbar)
- [x] Context-sensitive via `is_valid` callback
- [x] No default hotkey (suggested binding in README)
- [x] No persistent side panel -- preview via custom popup (ADR-0027)

## Docs
- [x] README.md with settings, API, usage examples, suggested hotkey
