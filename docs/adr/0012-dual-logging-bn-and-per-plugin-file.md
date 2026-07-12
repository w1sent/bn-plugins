# Dual logging: BN log + per-plugin file, level via BN settings

Plugins log user-facing messages (warnings, summaries) to BN's built-in log
console and full debug traces (agent output, prompt/response dumps, error
stacks) to `~/.binaryninja/logs/<plugin>.log`. Log level is configured via
BN's settings menu or programmatic override. `core/` provides a
`get_logger(name)` helper that sets up both outputs.