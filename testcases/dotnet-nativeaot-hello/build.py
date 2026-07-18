#!/usr/bin/env python3
"""Build the dotnet-nativeaot-hello testcase binary.

Usage:
    python build.py                # build nativeaot_hello(.exe) next to this script
    python build.py requirements   # print build dependencies
"""

import platform
import shutil
import subprocess
import sys
from pathlib import Path

_DIR = Path(__file__).resolve().parent


def requirements():
    print(".NET 8 SDK (or newer) with the NativeAOT-LLVM/ILCompiler workload:")
    print("  https://learn.microsoft.com/dotnet/core/deploying/native-aot")
    print("Linux:   apt install clang zlib1g-dev  (native toolchain NativeAOT compiles through)")
    print("macOS:   xcode-select --install")
    print("Windows: Visual Studio 'Desktop development with C++' workload")
    print("`dotnet` must be on PATH; the project pins net8.0 with <PublishAot>true</PublishAot>.")


def _runtime_identifier():
    system = platform.system()
    machine = platform.machine().lower()
    arch = "arm64" if machine in ("arm64", "aarch64") else "x64"
    if system == "Linux":
        return f"linux-{arch}"
    if system == "Darwin":
        return f"osx-{arch}"
    if system == "Windows":
        return f"win-{arch}"
    print(f"unrecognized platform {system}/{machine} -- pass a runtime identifier manually", file=sys.stderr)
    sys.exit(1)


def build():
    dotnet = shutil.which("dotnet")
    if dotnet is None:
        print("no `dotnet` CLI found on PATH -- see `python build.py requirements`", file=sys.stderr)
        sys.exit(1)

    rid = _runtime_identifier()
    cmd = [
        dotnet,
        "publish",
        str(_DIR / "NativeAotTestcase.csproj"),
        "-c",
        "Release",
        "-r",
        rid,
        "--self-contained",
        "true",
        "-o",
        str(_DIR / "bin"),
    ]
    print("running:", " ".join(cmd))
    subprocess.run(cmd, check=True)

    out_name = "nativeaot_hello.exe" if rid.startswith("win-") else "nativeaot_hello"
    built = _DIR / "bin" / out_name
    if not built.exists():
        print(f"expected output not found at {built}", file=sys.stderr)
        sys.exit(1)

    print(f"built -> {built}")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "requirements":
        requirements()
    else:
        build()
