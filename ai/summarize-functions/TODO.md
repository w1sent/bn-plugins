# summarize-functions — Implementation TODO

## Commands
- [ ] "Summarize Function" — context-aware: current function / selection / all user functions

## Behavior
- [ ] Summary written as a comment at the top of the function (BN-native display)
- [ ] No side panel — comments are visible inline in disassembly
- [ ] Single undo action wrapping the entire batch (BN's built-in undo)
- [ ] Progress bar + per-item log + completion notification (non-blocking)
- [ ] Cancel via progress bar button
- [ ] Tag summarized functions with "AI Summarized" tag type
- [ ] No confidence scores displayed
- [ ] Log message on load: provider, model

## API (`api.py`)
- [ ] `summarize_function(bv, func, *, provider=None, mode=None, options=None) -> SummarizeResult`
- [ ] `summarize_functions(bv, funcs, *, provider=None, mode=None, options=None) -> list[SummarizeResult]`
- [ ] `summarize_all(bv, *, provider=None, mode=None, options=None) -> list[SummarizeResult]`
- [ ] `api.help()` — summary of all functions
- [ ] `async_run=True` returns Future-like object
- [ ] All functions fully type-hinted
- [ ] Follow BN's exception/None convention

## Settings (BN native)
- [ ] `summarize_functions.provider` (string, default `""` → use ai-config default)
- [ ] `summarize_functions.mode` (enum: `"single"` / `"multi"`, default `"single"`)
- [ ] `summarize_functions.config_path` (string, default `~/.binaryninja/summarize-functions.json`)

## UI
- [ ] Register on all surfaces (context menu, command palette, toolbar)
- [ ] Context-sensitive via `is_valid` callback
- [ ] No default hotkey (suggested binding in README)
- [ ] No side panel — summaries visible as function comments

## Docs
- [ ] README.md with settings, API, usage examples, suggested hotkey
