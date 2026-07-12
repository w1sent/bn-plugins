# relevance — Agentic relevance tagging and path analysis

## Scope
- [ ] Deepagents-based agent that explores the binary and identifies relevant functions
- [ ] Tag functions with relevance level and explanation
- [ ] Annotate *why* a function is relevant (e.g. "crypto — uses AES constants", "network — calls send()", "parser — processes input buffer")
- [ ] Identify and rank relevant execution paths through the binary
- [ ] Integrate with node-canvas: display relevant paths with color coding

## Commands
- [ ] "Analyze Relevance" — context-aware: current function / selection / all functions
- [ ] "Show Relevant Paths" — opens node-canvas with color-coded relevant paths (if node-canvas installed)
- [ ] "Explain Relevance" — shows the agent's reasoning for a tagged function

## Behavior
- [ ] Agentic (deepagents): multi-step exploration, planning, reflection
- [ ] Agent examines: function disassembly, cross-references, constants, strings, call graph
- [ ] Output: relevance tags on functions with category and explanation
- [ ] Relevance categories: crypto, networking, parsing, anti-analysis, I/O, auth, logging, etc.
- [ ] Relevance levels: critical, high, medium, low
- [ ] Path analysis: traces call chains from entry points through relevant functions
- [ ] Tag type: "AI Relevance" with category and level in tag data
- [ ] Log message on load: provider, model

## API (`api.py`)
- [ ] `analyze_relevance(bv, *, provider=None, options=None) -> RelevanceResult`
- [ ] `get_relevant_functions(bv, min_level="medium") -> list[RelevantFunction]`
- [ ] `get_relevant_paths(bv) -> list[RelevantPath]`
- [ ] `get_relevance(bv, func) -> RelevantFunction | None`
- [ ] `api.help()`
- [ ] `async_run=True` returns Future-like object
- [ ] All functions fully type-hinted
- [ ] Follow BN's exception/None convention

### Types
- [ ] `RelevantFunction(func: Function, level: str, category: str, explanation: str)`
- [ ] `RelevantPath(functions: list[Function], score: float, description: str)`
- [ ] `RelevanceResult(functions: list[RelevantFunction], paths: list[RelevantPath])`

## Settings (BN native)
- [ ] `relevance.provider` (string, default `""` → use ai-config default)
- [ ] `relevance.mode` (enum: `"single"` / `"multi"`, default `"multi"`)
- [ ] `relevance.config_path` (string, default `~/.binaryninja/relevance.json`)

## UI
- [ ] Register on all surfaces (context menu, command palette, toolbar)
- [ ] Context-sensitive via `is_valid` callback
- [ ] No default hotkey (suggested binding in README)
- [ ] No side panel — relevance visible via tags + node-canvas integration
- [ ] Progress bar + per-item log + completion notification (non-blocking)
- [ ] Cancel via progress bar button

## node-canvas integration
- [ ] If node-canvas is installed, "Show Relevant Paths" opens a canvas
- [ ] Functions placed as nodes, edges for call relationships
- [ ] Color coding by relevance level: red (critical), orange (high), yellow (medium), grey (low)
- [ ] Edge thickness by path score
- [ ] Group nodes by category

## Docs
- [ ] README.md with settings, API, usage examples, suggested hotkey
