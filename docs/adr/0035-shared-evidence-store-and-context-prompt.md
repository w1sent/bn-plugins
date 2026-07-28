# Shared evidence store + AI context prompt: core-hosted, bndb-persisted, manual-trigger

To give every AI plugin a condensed, shared understanding of the loaded
sample (detected frameworks, libraries, other high-level metadata) without
each one re-exploring the binary from scratch, deterministic detectors
(`frameworks/*`, YARA) and an optional AI "enhancer" agent write into a
shared evidence store, which in turn feeds a cached "context prompt"
injected into every other AI tool's prompts.

**Location**: both live in `core/` as plain read/write helpers (like
`core/framework_status.py`), not a new plugin. Every plugin already
vendors its own copy of `core/` (ADR-0001), so this reuses that channel
instead of introducing an inter-plugin dependency (ADR-0014).

**Storage**: `bv.store_metadata()` / `bv.get_metadata()`, so data travels
with the `.bndb` — the same mechanism `ux/node-canvas/persistence.py`
already uses (ADR-0029), not a sidecar file.

**Evidence store** (`core/evidence.py`): one metadata key per detector,
`core.evidence.<detector_id>` → `{findings, last_run}`. No
`detector_version` field, and no central registry of detector IDs —
consumers discover entries by prefix-scanning `bv.metadata` (which returns
every stored key). This lets a single detector be rerun and overwrite only
its own key, and avoids requiring every plugin to be on the same `core/`
vendor version to agree on a shared schema.

**Context prompt**: a separate metadata key, distinct from the evidence
store, holding a deterministic baseline plus an optional AI-enhancer
narrative. It has two sub-fields: `raw_enhancer_output` (freely overwritten
by reruns) and `user_edit` (written only by the user, and used in
preference to `raw_enhancer_output` whenever present) — so a rerun can
never silently clobber a manual edit. A passive staleness flag compares the
context prompt's cached `last_run` against the newest `last_run` across
`core.evidence.*`; it is surfaced to the user but never triggers a rerun by
itself.

**Consumers are read-only**: `ai/auto-rename`, `ai/suggest-structs`, and
similar tools only ever read whatever context prompt is currently cached
(even if empty or stale) when building their own prompts. They never
invoke the enhancer themselves, including on first use with no cache yet —
running an exploratory agent is a cost/time decision the user makes
explicitly.

**UI**: the interactive view (AI/deterministic output above, user/used
context below, "run analysis" and "copy to user input" actions) is its own
plugin that calls into `core.evidence` / `core` context-prompt helpers,
not code living in `core` itself. `core` stays limited to the tiny,
universally-shared status-bar-style primitive (per ADR-0028's reasoning
for why the framework status indicator is core-worthy but heavier UI is
not); a full editable dual-pane view is exactly the kind of thing that
doesn't belong there.

Rejected: a single combined evidence+context blob (forces structured
consumers to parse prose, and detectors to produce prose they don't have);
a central detector registry requiring synchronized `core/` versions across
plugins (unnecessary once prefix-scanning `bv.metadata` works); automatic
cache invalidation when evidence changes (risks silently triggering
expensive LLM exploration as a side effect of an unrelated detector
rerun); letting consumer plugins trigger the enhancer on first use
(same silent-cost concern).
