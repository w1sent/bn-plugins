# AI error handling: retry with configurable backoff, warnings, summary

Transient AI failures (timeout, rate limit) are retried with configurable
exponential backoff steps. The first two failures print warnings to BN's
log. Permanent failures (bad config, model not found) show a one-time error.
After a batch operation, a summary is logged ("3 renamed, 2 failed — see
log"). Full error traces go to the per-plugin log file. Retry/backoff logic
lives in `core/` so all AI plugins share it.