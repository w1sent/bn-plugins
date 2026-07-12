# Auto Rename

AI-driven variable and function renaming using LLMs.

## Commands

| Command | Context | Description |
|---|---|---|
| Auto Rename | Function (right-click) | Rename a single function |
| Auto Rename (Selection) | Selection (right-click) | Rename selected functions |
| Auto Rename (Filtered) | Command palette | Rename functions matching a regex |
| Auto Rename All | Toolbar / Command palette | Rename all auto-named functions, using the `auto_rename.*` settings |
| Auto Rename All (Choose Strategy) | Command palette | Rename all auto-named functions, picking ordering/concurrency for this run only (not persisted) |

## Settings

| Setting | Type | Default | Description |
|---|---|---|---|
| `auto_rename.provider` | string | `""` | Provider name from `ai-config.json`; empty = use default |
| `auto_rename.mode` | string | `"single"` | Agent mode: `single` (langchain) or `multi` (deepagents) |
| `auto_rename.config_path` | string | `~/.binaryninja/auto-rename.json` | Path to complex config file |
| `auto_rename.ordering` | string | `"default"` | Scheduling order for bulk renaming (see below) |
| `auto_rename.concurrency_mode` | string | `"sequential"` | `sequential` or `fixed-pool` |
| `auto_rename.concurrency_workers` | int | `3` | Max concurrent LLM calls when `concurrency_mode` is `fixed-pool` |

## Scheduling strategies

Bulk renaming (`Auto Rename All`, `Auto Rename (Selection)`, `Auto Rename (Filtered)`, `rename_functions`/`rename_all`/`rename_filtered`) is controlled by two independent axes:

**Ordering** — which function is renamed next:

| Ordering | Behavior |
|---|---|
| `default` | No reordering |
| `leaves-first` | Fewest callees first (ties: address ascending) |
| `top-down` | BFS from `bv.entry_function`; falls back to the zero-caller root set if there's no entry function |
| `local-breadth` | BFS from the current function through its callees, current function first |
| `local-bottom-up` | Current function's callee subtree, deepest leaf first, current function last |
| `local-up` | BFS from the current function through its callers, closest first |
| `export-down` | Root-major BFS from each exported function, address order, first-touch wins |
| `info-gain` | Most callers first (ties: address ascending) |

`local-breadth`, `local-bottom-up`, and `local-up` need an anchor (the current function); if none is available, the command shows an error instead of renaming. For `Auto Rename (Selection)`, traversal is confined to the selected functions — anything unreachable from the anchor within that set sorts last instead of erroring.

**Concurrency** — how many rename requests run at once: `sequential` (one at a time) or `fixed-pool` (`concurrency_workers` concurrent LLM calls via a thread pool).

Ordering under `fixed-pool` is best-effort: functions are *submitted* in order, but with more than one worker there's no guarantee they *finish* in that order. `leaves-first`, `local-bottom-up`, and `info-gain` rely on a callee/deeper function finishing before its dependent is renamed to get better context — combining one of these with `fixed-pool` and more than one worker logs a warning that this benefit may be degraded. `sequential` always preserves ordering exactly.

Use **Auto Rename All (Choose Strategy)** to pick ordering/concurrency for a single run without changing the persisted settings.

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