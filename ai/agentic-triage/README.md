# Agentic Triage

AI-generated sample context prompt (the "AI sample-context prompt" /
"AI-enhancer" TODO), viewable and editable in a dedicated **Agentic Triage**
view -- the same view-selector dropdown Linear/Graph/Triage live in, not a
sidebar dock widget. See
[docs/adr/0035-shared-evidence-store-and-context-prompt.md](../../docs/adr/0035-shared-evidence-store-and-context-prompt.md).

## Opening the view

Open a binary, then use the view-type selector at the top of the tab
(next to Linear/Graph/Triage) and pick **Agentic Triage**.

## What it shows

- **AI / Deterministic Output** (top, read-only): whichever is freshest --
  the AI-enhancer's last output, or (if it's never run) the deterministic
  baseline rendered straight from `core.evidence`'s detector findings.
- **User / Used Context** (bottom, editable): what every other AI plugin
  (`ai/auto-rename`, `ai/suggest-structs`, ...) actually reads via
  `core.context.get_context_prompt()`. Edit it directly and click
  **Save Edit**, or click **Copy to User Input ↓** to pull the AI output
  down as a starting point. **Revert to AI Output** discards your edit.
- A staleness warning appears if a detector has recorded evidence more
  recently than the AI-enhancer's last run -- purely informational, it
  never triggers a rerun on its own.

## Enhancement passes

Both are optional -- with no evidence and no enhancer output, the view
just shows the deterministic baseline (which may be empty if no detector
has run yet).

| Button | What it does |
|---|---|
| Quick Enhance | One LLM call over curated evidence + cheap structural facts (entry point, imports/exports, sample strings). No exploration -- fast and cheap. |
| Run Full Analysis | A read-only agent investigates the binary (functions, imports/exports, strings, disassembly) before summarizing. Slower/costlier, more thorough. |

Both are capped to `agentic_triage.max_summary_tokens` (approximate,
word-count based) -- configurable in Settings, along with
`agentic_triage.agent_max_steps` (full-analysis tool-call budget) and
`agentic_triage.provider` (which `ai-config.json` provider to use).

## Usage

1. **Install the plugin** if you haven't: `python scripts/install.py --link`
   (dev symlink mode) or `python scripts/install.py` (copy mode), then
   (re)start Binary Ninja. Confirm it loaded by checking the log for
   `agentic-triage loaded`.
2. Open a binary and let a framework/detector plugin run (or just click
   **Quick Enhance** / **Run Full Analysis** directly -- the baseline is
   simply empty until a detector has recorded evidence).
3. Switch to the **Agentic Triage** view via the view-type selector.
