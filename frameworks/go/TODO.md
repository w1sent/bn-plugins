# go — Go binary runtime metadata support

## Scope
- [ ] Parse Go binaries (ELF/Mach-O/PE)
- [ ] Extract pclntab (function symbol table), type descriptors, module info
- [ ] Reconstruct interface types, method sets, and type hierarchies
- [ ] Map into BN's type/symbol system

## Notes
- Go binaries have extensive runtime metadata: pclntab, moduledata, typelinks
- `runtime.*` symbols are always present and well-structured
- Type descriptors include struct layouts, interface method tables
- Existing tools: GoReSym, go_parser, IDAGolangHelper
- Rich metadata comparable to Flutter/Dart — good candidate for early implementation
