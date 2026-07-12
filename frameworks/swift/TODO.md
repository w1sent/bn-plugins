# swift — Swift binary metadata support

## Scope
- [ ] Parse Swift binaries (Mach-O/ELF)
- [ ] Extract type descriptors, protocol conformance tables, method dispatch tables
- [ ] Reconstruct class hierarchies, protocol relationships, enum layouts
- [ ] Map into BN's type/symbol system

## Notes
- Swift binaries have extensive ABI-stable metadata: type descriptors, protocol descriptors
- Metadata format is documented (Swift ABI docs)
- Method dispatch: vtable (classes), witness tables (protocols)
- Existing tools: swift-demangle, dsdump, SwiftTypeDump
- Most relevant on Apple platforms, but Swift on Linux/Windows also has metadata
