# Auto Rename

AI-driven variable and function renaming using LLMs.

## Commands

| Command | Context | Description |
|---|---|---|
| Auto Rename | Function (right-click) | Rename a single function |
| Auto Rename (Selection) | Selection (right-click) | Rename selected functions |
| Auto Rename (Filtered) | Command palette | Rename functions matching a regex |
| Auto Rename All | Toolbar / Command palette | Rename all auto-named functions |

## Settings

| Setting | Type | Default | Description |
|---|---|---|---|
| `auto_rename.provider` | string | `""` | Provider name from `ai-config.json`; empty = use default |
| `auto_rename.mode` | string | `"single"` | Agent mode: `single` (langchain) or `multi` (deepagents) |
| `auto_rename.config_path` | string | `~/.binaryninja/auto-rename.json` | Path to complex config file |
| `auto_rename.parallel` | bool | `false` | Process functions in parallel |
| `auto_rename.concurrency` | int | `3` | Max concurrent LLM calls |

## API

```python
from ai.auto_rename import api

# Rename a single function
result = api.rename_function(bv, func)

# Rename all auto-named functions
results = api.rename_all(bv)

# Rename with a specific provider
results = api.rename_all(bv, provider="openai")

# Async (non-blocking) with completion callback
api.rename_all(bv, async_run=True, on_complete=my_callback)

# Async with handle
handle = api.rename_all(bv, async_run=True)
handle.done()  # bool
results = handle.result(timeout=120)  # blocks until done
```

For full API reference, call `api.help()` in BN's Python console.

## Suggested Hotkeys

| Action | Suggested binding |
|---|---|
| Auto Rename All | Ctrl+Shift+R |
| Auto Rename | Ctrl+R |

Configure in BN's Settings → Hotkeys → Auto Rename.

## Dependencies

- `core/` (vendored on install)
- `langchain` + `langchain-ollama` (default, local)
- `langchain-openai` (optional, for cloud providers)
- `langchain-anthropic` (optional, for Claude)

## AI Config

By default, the plugin uses Ollama at `localhost:11434` with `llama3.1:8b`.
Create `~/.binaryninja/ai-config.json` to configure providers:

```json
{
  "default": "local",
  "providers": {
    "local": {
      "type": "ollama",
      "model": "llama3.1:8b",
      "endpoint": "http://localhost:11434"
    },
    "openai": {
      "type": "openai",
      "model": "gpt-4o"
    }
  }
}
```

API keys are read from environment variables (`OPENAI_API_KEY`, etc.).