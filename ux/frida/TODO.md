# frida — Frida integration for Binary Ninja

## Scope
- [ ] Embedded Frida script editor with syntax highlighting
- [ ] Attach/spawn Frida on target process from within BN
- [ ] Context-sensitive snippet injection: right-click function → "Hook with Frida"
- [ ] Snippet library: pre-built templates for common tasks (hook, trace, replace, dump)
- [ ] Shortcuts to trigger snippet injection into the active script
- [ ] Script output/log visible in BN panel
- [ ] Sync addresses between BN and Frida (ASLR slide handling)

## Commands
- [ ] "Hook Function" — injects hook snippet for selected function
- [ ] "Trace Calls" — injects call-tracing snippet
- [ ] "Replace Implementation" — injects replacement snippet
- [ ] "Dump Arguments" — injects arg-dumping snippet
- [ ] "Attach to Process" — opens process picker, attaches Frida
- [ ] "Run Script" — executes the current script

## API (`api.py`)
- [ ] `attach(bv, process) -> FridaSession`
- [ ] `hook_function(session, func) -> HookResult`
- [ ] `inject_snippet(session, snippet_name, **params)`
- [ ] `run_script(session, script_text)`
- [ ] `api.help()`
- [ ] All functions fully type-hinted

## Notes
- Requires `frida-tools` pip package (vendored per-plugin)
- Snippets are `str.format` templates like AI prompts — user can add custom snippets
- Snippet library lives in `snippets/` directory
- ASLR handling: read module base from Frida, compute offset
- Consider: Frida's `Interceptor` API for hooking, `Stalker` for tracing
