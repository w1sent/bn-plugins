# Per-plugin `.deps/` via `pip install -t` with a `sys.path` shim

Vendored deps are materialized at install time by running
`pip install -t <plugin_dir>/.deps -r <plugin>/requirements.txt`; the plugin's
`__init__.py` prepends `.deps/` to `sys.path` so both Binary Ninja's runtime
and the editor/LSP find them. Chosen over in-repo vendored source (repo
bloat, painful updates) and per-plugin virtualenvs (fights BN's plugin
loader). Offline installs remain possible later by adding a `wheels/` cache
without changing this model.