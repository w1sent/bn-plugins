# Results display: log to console + tag modified items

After an AI operation completes, results are logged to BN's console with full
detail (old name, new name, confidence). Each modified item (function, data)
is tagged with a plugin-specific `TagType` (e.g. "AI Renamed", "AI
Summarized") so the user can filter, browse, and audit automated changes via
BN's tag browser. A summary notification shows the count of changes and
failures.