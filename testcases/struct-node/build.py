#!/usr/bin/env python3
"""Build the struct-node testcase binary.

Usage:
    python build.py                # build node.bin next to this script
    python build.py requirements   # print build dependencies
"""

import shutil
import subprocess
import sys
from pathlib import Path

_DIR = Path(__file__).resolve().parent


def requirements():
    print("A C compiler (gcc or clang) on PATH.")
    print("Debian/Ubuntu: apt install gcc binutils")
    print("macOS:         xcode-select --install")
    print("Windows:       install MinGW-w64 or use WSL")
    print("(objcopy, from binutils, is optional -- used to strip one symbol")
    print(" so the data_<addr> auto-name scenario in trigger 3 is exercised)")


def build():
    cc = shutil.which("gcc") or shutil.which("clang") or shutil.which("cc")
    if cc is None:
        print("no C compiler found on PATH -- see `python build.py requirements`", file=sys.stderr)
        sys.exit(1)

    src = _DIR / "node.c"
    out = _DIR / "node.bin"
    # -O0: keep offset arithmetic close to source instead of letting the
    # optimizer fold/vectorize it into something BN's HLIL analysis (and
    # therefore suggest-structs' skeleton extraction) would struggle to
    # recover a clean struct shape from.
    cmd = [cc, "-O0", "-g0", "-fno-stack-protector", "-o", str(out), str(src)]
    print("running:", " ".join(cmd))
    subprocess.run(cmd, check=True)

    # Strip g_scratch's own symbol (only) so BN has no name for it and
    # falls back to data_<addr> -- see node.c's comment on g_scratch. If
    # objcopy isn't available, the binary still builds and works for
    # triggers 1/2; only the trigger-3 auto-name scenario is degraded (BN
    # will show it as g_scratch instead of data_<addr>).
    objcopy = shutil.which("objcopy")
    if objcopy:
        subprocess.run(
            [objcopy, "--strip-symbol=g_scratch", str(out)], check=True
        )
        print("stripped g_scratch symbol")
    else:
        print("objcopy not found -- g_scratch will keep its symbol name", file=sys.stderr)

    print(f"built -> {out}")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "requirements":
        requirements()
    else:
        build()
