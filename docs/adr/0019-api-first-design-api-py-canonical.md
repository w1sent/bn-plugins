# API-first design: `api.py` is canonical, commands wrap it

Plugins that are expected to be scripted (AI plugins, framework plugins)
expose a Python-idiomatic public API in `api.py`. This API takes proper
Python types (BN objects, dicts, enums), returns structured results, and is
the source of truth for the plugin's functionality. `__init__.py` registers
`PluginCommand` entries that call into `api.py` — not the other way around.
UX plugins provide an API only when other plugins or scripts would benefit
(e.g. a custom graph view exposing `add_node()`).