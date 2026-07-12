# wasm — WebAssembly bytecode support

## Scope
- [ ] Parse WebAssembly (.wasm) binaries
- [ ] Extract type section, import/export tables, function signatures
- [ ] Lift WASM bytecode to BNIL for analysis
- [ ] Map into BN's type/symbol system

## Notes
- WASM has a well-defined binary format with type sections
- Rich metadata: function signatures, import/export names, memory layout
- Could provide a BN Architecture subclass for WASM bytecode
- Growing ecosystem: browser, server-side (WASI), plugin systems
- Existing tools: wasmparser, wabt, wasm-decompile
