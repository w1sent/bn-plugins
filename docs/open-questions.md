# Open Questions

All questions from the initial session have been resolved.

## Resolved

- **Plugin versioning & metadata** → BN's native `plugin.json` + `x_min_core_version` (ADR-0008)
- **Testing strategy** → Per-plugin `tests/run.py` + shared `testcases/` with `build.py` (ADR-0009)
- **BN API version compatibility** → Minimum-only via `minimumbinaryninjaversion` (ADR-0010)
- **Error handling for AI failures** → Retry with configurable backoff, warnings, summary (ADR-0011)
- **Logging** → Dual: BN log + per-plugin file, level via BN settings (ADR-0012)
- **Prompt iteration workflow** → Hot-reload via mtime check in `load_prompt()` (ADR-0013)
- **Plugin dependency declarations** → All plugins independent for now (ADR-0014)
