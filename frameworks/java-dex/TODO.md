# java-dex — Dalvik/ART bytecode support

## Scope
- [ ] Parse DEX/ODEX files (Dalvik Executable)
- [ ] Reconstruct classes, methods, fields from DEX metadata
- [ ] Map into BN's type/symbol system
- [ ] Consider: ART OAT files (compiled DEX → native)

## Notes
- DEX format is well-documented, rich metadata: full type system, method signatures, string table
- Smali/baksmali as reference implementation
- ART runtime structures for OAT files: compiled code with metadata
- Common in Android APK reverse engineering
