# dotnet-nativeaot-hello

A small NativeAOT-published .NET binary exercising the shapes
`frameworks/dotnet-native-aot` recovers: a base class (`Animal`, deriving
from the implicit `System.Object`), a derived class (`Dog`) that overrides a
virtual method and adds a new one, an interface (`IGreeter`) implementation,
a frozen string literal, and a frozen `int[]` literal.

Not checked in prebuilt -- NativeAOT output is a multi-megabyte
self-contained native binary and the SDK is a heavy, platform-specific
dependency. Build it locally:

```
python build.py               # see build.py requirements first if `dotnet` isn't installed
```

Produces `bin/nativeaot_hello` (or `bin/nativeaot_hello.exe` on Windows).
