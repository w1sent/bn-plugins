# Per-plugin AI settings: provider, mode, config_path

Each AI plugin registers three settings via BN's native `Settings` API:
- `<plugin>.provider` — selects a named provider from `ai-config.json`; empty = use global default
- `<plugin>.mode` — `"single"` (langchain) or `"multi"` (deepagents)
- `<plugin>.config_path` — path to the plugin's complex config file

Enable/disable is handled by BN's plugin manager, not a setting. The
`provider` setting lets different plugins target different models (e.g. fast
local for auto-rename, capable cloud for suggest-structs) while all provider
definitions live in the shared `ai-config.json`.