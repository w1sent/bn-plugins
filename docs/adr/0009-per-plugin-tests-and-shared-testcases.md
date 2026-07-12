# Per-plugin `tests/run.py` + shared `testcases/` with `build.py`

Every plugin has a `tests/run.py` that runs inside Binary Ninja's GUI via
"Run Script". It loads test binaries from the shared `testcases/` directory
and exercises the plugin's functionality. `core/` unit tests live at
`tests/core/` and run with `pytest` outside BN (no BN dependency).

Each testcase directory under `testcases/<scenario>/` contains source files,
a `build.py` that builds the binary, and the built artifact. `build.py
requirements` prints the dependencies needed to build (package manager
commands or source URLs). Testcases are reusable across plugins and for
manual testing.

Tests are mandatory for every plugin.