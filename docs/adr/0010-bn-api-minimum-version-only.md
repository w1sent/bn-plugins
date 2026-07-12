# BN API version: minimum-only via native `minimumbinaryninjaversion`

Plugins declare BN API compatibility using BN's native
`minimumbinaryninjaversion` field in `plugin.json`. No maximum version or
tested-up-to field is added — BN's API is stable within major versions, and
a hard max creates maintenance busywork. If a specific BN version breaks a
plugin, the plugin checks at runtime and warns the user.

Rejected: `x_max_binaryninjaversion` (maintenance burden),
`x_tested_binaryninjaversion` (soft warning adds little value over runtime
check).