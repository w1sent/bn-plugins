# dotnet-native-aot — .NET NativeAOT compiled binary support

## Scope
- [ ] Parse NativeAOT-compiled .NET binaries (no CLR, no IL — native code)
- [ ] Reconstruct managed types from runtime metadata structures
- [ ] Map into BN's type/symbol system

## Notes
- NativeAOT emits native code with embedded runtime data structures
- Metadata: EEClass, MethodTable, interface dispatch maps, GC info
- Different from regular .NET — no IL, no JIT, no CLR loader
- Similar approach to Flutter: parse runtime structures, create BN types
