# Hex Visualizer — Selection-driven inspector panel

A sidebar panel that tracks whatever's currently selected in a hex/linear
view: a media preview when the selection's bytes match a known format
(with the full file carved out and previewed even if you only selected
its magic bytes), plus a fixed data-inspector table of common-type
interpretations of the selected bytes. See
[docs/adr/0037-hex-visualizer-inspector-panel.md](../../docs/adr/0037-hex-visualizer-inspector-panel.md)
for the design decisions behind this plugin.

## Opening the panel

Click the Hex Visualizer icon in Binary Ninja's sidebar (right side by
default). This is a `SidebarWidget`, not a custom view type -- it has no
state of its own and just re-renders on every selection change in
whichever pane it's attached to.

## What it shows

**Media preview** -- if the selection's bytes start with a recognized
format's magic bytes, a thumbnail preview is shown (PNG, JPEG, GIF, BMP,
ICO/CUR, WebP -- decoded via Qt's own image codecs, no extra dependency).
Detection also carves the full extent of the file by parsing its
container structure (PNG chunks, JPEG markers, GIF blocks, the RIFF/BMP
header's own size field, ICO's directory, or ISO-BMFF boxes), reading
beyond the selection as needed (bounded by `CARVE_MAX`, 16 MiB) -- so
selecting just the first byte or two of an embedded image is enough to
preview the whole thing, not just what you dragged over. ISO-BMFF
containers (MP4/MOV/...) are detected and carved for size, but shown as
metadata only (major/compatible brands) -- no frame/thumbnail decode, see
the ADR.

**Data inspector table** -- a fixed set of common-type interpretations of
the literal selected bytes (not the carved extent): int8-64 and float32/64
in both endiannesses, GUID (Windows/COM mixed-endian) and UUID (RFC 4122
big-endian) for 16+ byte selections, time32_t/time64_t (Unix timestamps,
both endiannesses) for 4+/8+ byte selections, DOS date/time (ZIP/FAT
packed format) for 4+ byte selections, hex, binary, and ASCII/UTF-8/UTF-16LE
string previews. Rows for types wider than the selection are omitted
rather than shown as garbage. Select one or more rows and press Ctrl+C
(or right-click → Copy) to copy them to the clipboard, tab-separated.

## API (`api.py`)

```python
import importlib
api = importlib.import_module("hex-visualizer.api")
result = api.inspect(bv, 0x1000, 8)
print(result.format_match, result.carved_length, len(result.data))
for row in result.rows:
    print(row.label, row.value)
```

`inspect(bv, start, length) -> InspectionResult` is the sidebar panel's
only dependency on plugin state -- it's plain Python with no
Qt/binaryninjaui import, so it works headlessly from `execute_script`
with no widget open (see `CONTEXT.md`'s "Developing and testing plugins"
section for the import dance BN's hyphenated plugin directory names need).

## Settings

None yet -- `READ_LIMIT`, `SNIFF_WINDOW`, and `CARVE_MAX` are fixed
constants in `api.py`/`formats.py`. See `TODO.md` if these need to become
configurable.
