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
| Auto Rename Variable | HLIL instruction (right-click) | Rename the variable referenced at this location |
| Auto Rename Variables (Current Function) | Function (right-click) | Rename all auto-named variables in the current function (function-level batch) |
| Auto Rename Variables (Selection) | Selection (right-click) | Rename auto-named variables in the selected functions (batch) |
| Auto Rename Variables (Filtered) | Command palette | Rename variables matching a regex, across the whole binary |
| Auto Rename All Variables | Toolbar / Command palette | Rename every auto-named variable in the binary (global batch) |

"Auto-named" for a variable means Binary Ninja hasn't recorded a user-supplied
name for it (`func.is_var_user_defined(var)` is false) -- this covers
default names regardless of convention (`var_10`, `arg1`, `rax_1`, ...).

## Settings

| Setting | Type | Default | Description |
|---|---|---|---|
| `auto_rename.provider` | string | `""` | Provider name from `ai-config.json`; empty = use default |
| `auto_rename.mode` | string | `"single"` | Agent mode: `single` (langchain) or `multi` (deepagents) |
| `auto_rename.config_path` | string | `~/.binaryninja/auto-rename.json` | Path to complex config file (auto-created with defaults on first use, see below) |
| `auto_rename.ordering` | string | `"default"` | Scheduling order for bulk renaming (see below) |
| `auto_rename.concurrency_mode` | string | `"sequential"` | `sequential` or `fixed-pool` |
| `auto_rename.concurrency_workers` | int | `3` | Max concurrent LLM calls when `concurrency_mode` is `fixed-pool` |
| `auto_rename.debug_logging` | bool | `false` | Log every LLM request (timestamp, plugin, provider/model, prompt) to `~/.binaryninja/llm-request.log` |

## Complex config file

The file at `auto_rename.config_path` is created automatically with default
values the first time a rename runs, if it doesn't already exist:

```json
{
  "custom_prompt": null,
  "custom_var_prompt": null,
  "temperature": 0.1,
  "backoff_steps": [1, 2, 4, 8]
}
```

| Key | Description |
|---|---|
| `custom_prompt` | Raw prompt template text overriding the bundled `prompts/rename.txt` (function renaming); `null` uses the bundled template |
| `custom_var_prompt` | Raw prompt template text overriding the bundled `prompts/rename_var.txt` (variable renaming); `null` uses the bundled template |
| `temperature` | Default LLM temperature, used when the resolved provider (`ai-config.json`) doesn't set its own |
| `backoff_steps` | Retry delays in seconds for failed rename attempts |

Templates (bundled or `custom_prompt`) use `$`-style placeholders (Python
`string.Template`, e.g. `$function_name`), not `str.format()` `{}` fields —
this lets the template freely contain literal `{`/`}` (e.g. the example
JSON output the model is asked to produce) without it being misparsed as a
format field. Available placeholders: `$function_name`, `$address`,
`$callers`, `$callees`, `$string_refs`, `$data_refs`, `$disassembly`.
Unknown/misspelled placeholders are left as-is rather than raising.

Any `RenameOptions` field passed via the API (`temperature`, `custom_prompt`)
takes precedence over this file. Keys omitted from an existing file fall
back to the defaults above, so adding a new default in a future version
doesn't require editing an existing config by hand.

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

## Variable renaming

Variable renaming works the same way as function renaming but targets local
variables and parameters (via the HLIL variable API) instead of function
symbols. It shares the `auto_rename.*` settings, the complex config file, and
the `auto_rename.concurrency_mode` / `auto_rename.concurrency_workers`
settings -- the `auto_rename.ordering` setting does **not** apply, since the
function-graph orderings (`leaves-first`, `local-breadth`, etc.) aren't
meaningful for variables. Variables are always processed in a fixed
`(function address, variable name)` order; `fixed-pool` concurrency runs
that many renames at once, same as for functions.

Prompts use a separate bundled template, `prompts/rename_var.txt`, with its
own placeholders: `$function_name`, `$function_address`, `$variable_name`,
`$variable_type`, `$usages` (the HLIL lines where the variable appears).

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

# Rename a single variable
result = api.rename_variable(bv, func, "var_10")

# Rename all auto-named variables in one function (function-level batch)
results = api.rename_variables(bv, func)

# Rename every auto-named variable in the binary (global batch)
results = api.rename_all_variables(bv)

# Rename variables matching a regex, confined to a set of functions
results = api.rename_filtered_variables(bv, r"^i\d*$", restrict_to=[func_a, func_b])
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
`~/.binaryninja/ai-config.json` is created automatically with these defaults
the first time a rename runs, if it doesn't already exist. Edit it to
configure additional providers:

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