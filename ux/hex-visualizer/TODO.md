# hex-visualizer — Selection-driven inspector panel

v1 shipped: sidebar panel tracking hex/linear-view selection, image
preview (PNG/JPEG/GIF/BMP/ICO/WebP via Qt's built-in codecs) with
full-file carving from a partial selection, ISO-BMFF metadata-only
detection, a fixed scalar data-inspector table (int8-64, float32/64,
GUID/UUID, time32_t/time64_t, DOS date/time, hex, binary, string
previews), and table copy-to-clipboard. See
[docs/adr/0037](../../docs/adr/0037-hex-visualizer-inspector-panel.md).

Deferred/remaining, per the ADR's explicit scope cuts and open TODO items:

- [ ] Video-frame/thumbnail decode for ISO-BMFF containers (MP4/MOV/...)
      -- currently metadata-only (major/compatible brands). Would need a
      vendored decoder (`av`/ffmpeg bindings) or Qt Multimedia's
      `QMediaPlayer`/`QVideoSink` frame-grab; explicitly out of scope for
      v1 (see ADR-0037's "Media preview" section).
- [ ] User-defined struct/pattern overlay (ImHex-pattern-language-style)
      over a selection, as an alternative/complement to the fixed scalar
      table -- explicitly deferred in the ADR; would want to reuse
      `ai/suggest-structs`' inference rather than reimplement struct
      inference here.
- [ ] Entropy/packing overlay -- ties into the separate root-level TODO
      item ("Entropy/packing overlay in hex editor"); natural fit for
      this same panel once built, not part of v1.
- [ ] Additional carveable formats beyond the current PNG/JPEG/GIF/BMP/
      ICO/WebP/ISO-BMFF set (e.g. ZIP/PE/ELF headers, audio formats) --
      add incrementally as concrete need comes up, following the same
      `formats.py` sniffer + `_carve_*` pattern.
- [ ] `READ_LIMIT`/`SNIFF_WINDOW`/`CARVE_MAX` (currently fixed constants
      in `api.py`/`formats.py`) as BN native settings, if a real workflow
      needs to tune them (e.g. very large embedded media, or tighter
      memory bounds on constrained machines).
- [ ] GIF/JPEG carving currently bails (returns `None`) on any block/
      marker structure it doesn't recognize rather than making a
      best-effort guess -- revisit if real-world samples turn up
      unrecognized-but-common variants worth handling explicitly.
