# UI: prefer BN-native display over custom UI

Before building a custom popup, side panel, or view, ask: "Can Binary Ninja or
another plugin already display this information in an easy-to-perceive way?"
If yes, use the existing mechanism:
- Function summaries → comments at function top (visible in disassembly)
- Struct suggestions → custom popup for preview, then apply (see ADR-0027:
  no programmatic pre-fill API exists for BN's native type editor)
- Class hierarchies → map into BN's existing type/symbol system if possible

Custom UI (popups, panels, views) is built only when BN's native display is
insufficient. The choice of UI surface (popup vs. panel vs. view) depends on
the specific use case and requires explicit discussion.

Rejected: side panels for summarize-functions (comments suffice), side
panels for suggest-structs (type editor or popup suffices for preview).