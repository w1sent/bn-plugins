# suggest-structs — Implementation TODO

## Commands
- [ ] "Suggest Struct" — context-aware: current data / selection / all data regions
- [ ] "Suggest Struct (Batch)" — batch mode, applies directly without preview

## Behavior
- [ ] Preview before apply (except batch mode): open BN's type editor with pre-filled struct
- [ ] Fallback: custom popup if BN's type editor can't be driven programmatically
- [ ] Single undo action wrapping the entire batch (BN's built-in undo)
- [ ] Progress bar + per-item log + completion notification (non-blocking)
- [ ] Cancel via progress bar button
- [ ] Tag created structs with "AI Struct" tag type
- [ ] No confidence scores displayed
- [ ] Log message on load: provider, model

## API (`api.py`)
- [ ] `suggest_struct(bv, addr, *, provider=None, mode=None, options=None) -> StructResult`
- [ ] `suggest_structs(bv, addrs, *, provider=None, mode=None, options=None) -> list[StructResult]`
- [ ] `suggest_all(bv, *, provider=None, mode=None, options=None) -> list[StructResult]`
- [ ] `api.help()` — summary of all functions
- [ ] `async_run=True` returns Future-like object
- [ ] All functions fully type-hinted
- [ ] Follow BN's exception/None convention

## Settings (BN native)
- [ ] `suggest_structs.provider` (string, default `""` → use ai-config default)
- [ ] `suggest_structs.mode` (enum: `"single"` / `"multi"`, default `"multi"`)
- [ ] `suggest_structs.config_path` (string, default `~/.binaryninja/suggest-structs.json`)

## UI
- [ ] Register on all surfaces (context menu, command palette, toolbar)
- [ ] Context-sensitive via `is_valid` callback
- [ ] No default hotkey (suggested binding in README)
- [ ] No persistent side panel — preview via type editor or popup

## Docs
- [ ] README.md with settings, API, usage examples, suggested hotkey
