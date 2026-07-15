# Struct preview via custom popup, not BN's native type editor

ADR-0024 said struct suggestions should preview via "BN's type editor." Investigation
of the actual Binary Ninja Python API (`$BN_SRC/python/`,
`binaryninjaui`) during suggest-structs design found no programmatic way to open or
pre-fill BN's native Create-New-Types dialog — `binaryninjaui`'s Python surface ships
as a compiled module with no `TypeEditor`/`StructureEditor` class, and no such API is
documented. There is no "fallback" case to design for: a custom popup is the only
preview mechanism available, not a degraded second choice.

suggest-structs previews via `binaryninja.interaction`'s free-text multiline form,
pre-filled with the LLM's proposed struct rendered as C syntax. The user can hand-edit
the text before accepting. On accept, the text is round-tripped through
`bv.parse_type_string` (the same validation path BN's own UI uses for typed input)
before `define_user_type` / `create_user_var` are called — so an invalid edit fails
the same way it would in BN's native UI, rather than being silently accepted.

This supersedes ADR-0024's line "Struct suggestions → BN's type editor for preview";
the rest of ADR-0024 (prefer BN-native display when a mechanism genuinely exists)
still holds.
