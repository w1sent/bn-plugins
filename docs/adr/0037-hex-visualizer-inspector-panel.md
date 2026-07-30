# hex-visualizer: sidebar inspector driven by hex-view selection

New `ux/hex-visualizer` plugin: selecting a byte range in BN's built-in hex
editor (or Linear/Disassembly view) updates a sidebar panel showing a
media preview (image formats, later video-container metadata) plus a
data-inspector table (common-type interpretations of the selected bytes),
per the TODO's "Hex-editor visualizer side panel" item.

## UI surface: sidebar widget, not a popup

Per ADR-0024, checked first whether BN's native display already covers
this — it doesn't; there's no built-in "interpret these bytes as an image
or a set of scalar types" view. A sidebar widget (not a popup) is the
right surface because the content is meant to stay visible and update
continuously as the user moves the selection, the same reasoning
`node-canvas` used for its own panel. A popup would have to be
re-triggered per selection; a permanent panel just tracks it.

## Selection-tracking mechanism

Verified live against a running BN instance (via `binja-mcp`,
`binaryninjaui` module) rather than guessing from docs:

- `SidebarWidget.notifyViewChanged(ViewFrame*)` fires when the active
  view/tab changes — used to capture and hold the current `ViewFrame`.
- `SidebarWidget.notifyOffsetChanged(uint64_t)` fires on cursor/selection
  movement within the active view, including the hex editor. This is the
  update trigger; it does not itself carry the selection range.
- `ViewFrame.getSelectionOffsets()` returns the actual `(start, end)`
  selection range at call time, and `ViewFrame.getCurrentBinaryView()`
  returns the `BinaryView` to read bytes from. Both are called from
  inside `notifyOffsetChanged`, not derived from the offset argument.
- No dedicated Qt `selectionChanged` signal exists on `HexEditor` (checked
  `dir()` for `Signal`-typed attributes — only generic `QWidget` signals
  are present), so polling via `notifyOffsetChanged` is the only hook,
  matching how BN's own sidebar widgets (e.g. cross-reference, strings)
  stay in sync — not a custom mechanism invented for this plugin.

`SidebarContextSensitivity.PerPaneSidebarContext` is used (one widget
instance reused per pane, renotified on pane switch) rather than
`SelfManagedSidebarContext` (what `node-canvas` uses, because a canvas is a
per-`bv` document the widget owns and tracks itself) — this panel has no
state of its own to own; it's a pure read-through view of "whatever's
selected right now," so BN's per-pane widget lifecycle is sufficient and
simpler than self-managing a `bv`-keyed registry.

## Format detection: byte-content sniffing, not extension/BN-type based

The selection is an arbitrary byte range inside a loaded binary — there's
no filename or BN type to key off. Detection (`formats.py`) is pure
magic-byte/structure sniffing (PNG signature, JPEG SOI/EOI + marker walk,
GIF87a/89a header, BMP `BM` + header size sanity check, ISO-BMFF `ftyp`
box for MP4/MOV/similar containers), independent of `binaryninjaui` so
it's unit-testable headlessly like other plugins' `formats.py`/model
modules (`node-canvas` sets the precedent).

## Media preview: Qt's own image codecs, no new dependency

`QImage`/`QPixmap.loadFromData` already decode PNG/JPEG/GIF/BMP from raw
bytes — Qt is provided by BN itself, so previewing these formats needs no
vendored dependency (checked: no plugin in this repo vendors Pillow, and
none is needed here).

MP4/ISO-BMFF containers are **out of scope for actual frame/thumbnail
rendering in v1** — decoding a video frame would need either a vendored
decoder (`av`/ffmpeg bindings) or Qt Multimedia's `QMediaPlayer` +
`QVideoSink` frame-grab, both nontrivial dependencies/plumbing for a
first cut. v1 shows structural metadata instead (major/minor brand,
compatible brands, box layout) parsed by the same `formats.py` sniffer.
Actual video-frame thumbnailing is deferred to `ux/hex-visualizer/TODO.md`
as a follow-up, not silently dropped.

## Data inspector: fixed common-type table, not user-defined structs

For the non-preview part of the panel, the selection is decoded as a
fixed table of scalar interpretations (int8/16/32/64 signed/unsigned in
both endiannesses, float32/64, ASCII/UTF-8/UTF-16LE string preview) —
this covers the "hex/ASCII/common-type interpretations" scope agreed with
the user, and needs no schema. Applying a user- or AI-suggested *struct*
layout over a selection (ImHex-pattern-language-style) is explicitly
deferred — it's a much larger feature (would want to reuse
`ai/suggest-structs`' inference rather than duplicate it) and isn't needed
for the inspector to be useful on its own.

## Considered and rejected

- **Reuse/extend BN's own hex editor widget subclass** instead of a
  separate sidebar panel — BN's `HexEditor` is a `binaryninjaui` builtin
  class, not something this repo can subclass into a custom view; a
  sidebar panel that reads the hex editor's selection is the available
  extension point.
- **Full video decoding for MP4 in v1** — rejected for now; see above.
  Static ISO-BMFF metadata still gives useful signal (container format,
  brand) without the dependency weight.
- **User-defined struct/pattern overlay in v1** — rejected for now;
  bigger feature, deferred, would lean on `ai/suggest-structs` rather than
  reimplement struct inference here.
