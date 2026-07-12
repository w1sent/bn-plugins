# dotnet — .NET CLR bytecode support

## Scope
- [ ] Parse .NET PE files with CLR metadata
- [ ] Reconstruct managed types, methods, and IL bytecode
- [ ] Map into BN's type/symbol system

## Notes
- Rich metadata: full type system, method signatures, string heap, GUID heap
- IL bytecode can be lifted to BNIL for analysis
- Consider: C++ tool for metadata extraction (like blutter) or pure Python via dnlib/AsmResolver bindings
