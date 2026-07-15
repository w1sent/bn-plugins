# Suggest Structs

AI-driven struct suggestion from pointer access patterns.

## Commands

| Command | Context | Description |
|---|---|---|
| Suggest Struct | Address (right-click) | Suggest a struct for the pointer variable nearest the cursor |
| Suggest Struct (Selection) | Selection (right-click) | Seed a struct sized to the selected byte range, then refine it |
| Suggest Struct (Batch) | Toolbar / Command palette | Sweep every candidate pointer variable and untyped global, applying directly |

`Suggest Struct` and `Suggest Struct (Selection)` preview before applying
when `suggest_structs.mode` is `single` (see [Preview](#preview) below).
`Suggest Struct (Batch)` never previews and honors whichever mode is
configured per candidate.

## How struct derivation works

A deterministic pass over the target variable's HLIL uses builds an
*advisory* skeleton — offsets, sizes, and inferred types from real accesses
(`var->field_0x8`, etc.). This skeleton is handed to the LLM as context, not
a hard constraint: Binary Ninja's own analysis can miss or misattribute
accesses, so the LLM may deviate from it when surrounding context (string
refs, data refs, calling conventions) suggests a better layout.

The LLM's output is a full C struct definition (free text), not JSON — the
same format used for the preview popup and for existing-type reuse. The LLM
is given the binary's existing user-defined type names/definitions as
context and decides whether to reference one instead of defining a
near-duplicate.

## Modes

- **`single`** (langchain): one LLM call per suggestion, fixed context
  bundle (skeleton + HLIL + string/data refs + existing type names).
- **`multi`** (deepagents, default): an agent with tools to investigate
  related/nested variables, look up existing types, and submit/apply/undo
  struct definitions across multiple steps, terminating by calling
  `confirm_edits`. The agent mutates the binary live during its session,
  wrapped in one BN undo boundary; if the session ends without calling
  `confirm_edits` (step budget exceeded, error, or cancellation), every
  edit made that session is rolled back — see `agent.py`.

Batch mode's per-candidate cost with `multi` mode is one full agent session
per candidate; this is accepted cost when the setting is configured that
way, not overridden to `single` for batch runs.

## Preview

`suggest_structs.mode = single`'s non-batch commands preview before
applying: the LLM's proposed struct is shown in an editable free-text
popup (C syntax) before anything is written to the binary. This is a custom
popup, not Binary Ninja's native type editor — investigation during this
plugin's design found no programmatic way to pre-fill BN's native
Create-New-Types dialog (see ADR-0027). Accepting round-trips the (possibly
edited) text through `bv.parse_type_string`, so an invalid edit fails the
same way it would in BN's own UI.

`multi` mode has no separate preview step for the single-item commands —
its own tool loop (`submit_struct`/`undo_struct`/`confirm_edits`) is the
interactive/correctable surface instead.

## Settings

| Setting | Type | Default | Description |
|---|---|---|---|
| `suggest_structs.provider` | string | `""` | Provider name from `ai-config.json`; empty = use default |
| `suggest_structs.mode` | string | `"multi"` | Agent mode: `single` (langchain) or `multi` (deepagents) |
| `suggest_structs.config_path` | string | `~/.binaryninja/suggest-structs.json` | Path to complex config file (auto-created with defaults on first use) |
| `suggest_structs.confidence_threshold` | int | `255` | `Type.confidence` at/above which a variable is skipped as already-typed during batch sweep |
| `suggest_structs.agent_max_steps` | int | `12` | Multi-mode agent tool-call budget per session |
| `suggest_structs.agent_max_structs_per_session` | int | `8` | Cap on `submit_struct` calls per multi-mode session |

## Complex config file

The file at `suggest_structs.config_path` is created automatically with
default values the first time a suggestion runs, if it doesn't already
exist:

```json
{
  "custom_prompt": null,
  "custom_agent_prompt": null,
  "temperature": 0.1,
  "backoff_steps": [1, 2, 4, 8]
}
```

| Key | Description |
|---|---|
| `custom_prompt` | Raw prompt template overriding the bundled `prompts/suggest_struct.txt` (single mode) |
| `custom_agent_prompt` | Raw system prompt overriding the bundled `prompts/agent_system.txt` (multi mode) |
| `temperature` | Default LLM temperature, used when the resolved provider doesn't set its own |
| `backoff_steps` | Retry delays in seconds for failed single-mode suggestion attempts |

Templates use `$`-style placeholders (Python `string.Template`), not
`str.format()` `{}` fields — struct examples in the prompts contain literal
braces that `str.format()` would misparse as format fields (see
`ai/auto-rename`'s history for the bug this avoids).

## API

```python
from ai.suggest_structs import api

# Suggest a struct for a pointer variable (preview text in single mode)
result = api.suggest_struct(bv, func.start, var_name="var_18")
if result.definition and not result.applied:
    applied = api.apply_definition(bv, func, var, result.definition)

# Seed a struct from a selection, then refine
result = api.suggest_struct_from_range(bv, selection_start, selection_length)

# Batch sweep every candidate
results = api.suggest_all(bv, async_run=True, on_complete=my_callback)
```

For full API reference, call `api.help()` in BN's Python console.

## Suggested Hotkeys

No default hotkey is registered. Configure in BN's Settings → Hotkeys →
Suggest Structs.

## Dependencies

- `core/` (vendored on install)
- `langchain` + `langchain-ollama` (default, local)
- `langchain-openai` / `langchain-anthropic` / `langchain-google-genai` (optional, cloud providers)
- `deepagents` (multi mode)

## AI Config

Shared with other AI plugins — see `~/.binaryninja/ai-config.json`
(auto-created with an Ollama default on first use by any AI plugin).
