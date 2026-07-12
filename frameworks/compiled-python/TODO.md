# compiled-python — Compiled Python binary support

## Scope
- [ ] Parse PyInstaller, Nuitka, Cython, cx_Freeze compiled binaries
- [ ] Extract embedded Python bytecode (.pyc), module metadata
- [ ] Reconstruct module/function names and type information

## Notes
- PyInstaller: archives with CArchive/ZlibArchive format, contains .pyc files
- Nuitka: compiles Python to C++, then native — less metadata, more like native binary
- Cython: compiles .pyx to C extension modules — native code with Python C API calls
- .pyc files: Python bytecode with code objects, constants, names — rich metadata
- Focus on extracting and annotating, not decompiling Python bytecode
