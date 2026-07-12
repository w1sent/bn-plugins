# AI plugins write directly to the BN database

AI plugins mutate the Binary Ninja database directly (rename symbols, create
structs, set comments, change types) without a confirmation prompt or
suggestion-review UI. The user can undo changes via BN's built-in undo, so
the friction of a confirmation workflow isn't worth the protection.

Rejected: read-only suggestions with manual apply (adds UI overhead),
hybrid risk-threshold model (adds complexity without clear benefit given
undo exists).