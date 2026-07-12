# react-native — React Native / Hermes / JavaScriptCore support

## Scope
- [ ] Parse React Native bundles (Hermes bytecode or JavaScriptCore snapshots)
- [ ] Reconstruct function names, string table, object layouts
- [ ] Map into BN's type/symbol system

## Notes
- Hermes: Facebook's JS engine for React Native, emits bytecode (HBC format)
- JavaScriptCore: Apple's JS engine, used on iOS React Native, emits bytecode snapshots
- Both have rich metadata: function names, string tables, object shapes
- Hermes bytecode format is documented (hbc-parser exists)
- Consider: C++ tool for bytecode parsing (like blutter) or pure Python
