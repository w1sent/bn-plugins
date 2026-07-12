# unity-il2cpp — Unity IL2CPP metadata support

## Scope
- [ ] Parse Unity IL2CPP binaries + `global-metadata.dat`
- [ ] Reconstruct full type system, method names, string table from metadata
- [ ] Map into BN's type/symbol system

## Notes
- IL2CPP compiles C# to C++ then native; metadata is in a separate `global-metadata.dat` file
- Metadata format is well-documented and stable across Unity versions
- Contains: full type hierarchy, method signatures, string literals, field offsets
- Existing tools: Il2CppInspector, Il2CppDumper, Cpp2IL
- Very common in mobile games — high-value target
- Similar approach to Flutter: parse metadata file, create BN types and rename functions
