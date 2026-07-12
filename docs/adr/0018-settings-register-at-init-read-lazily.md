# Settings: register at init, read lazily

Plugin settings are registered once in `__init__.py` (so they appear in BN's
Settings UI) and read fresh on each command invocation via
`Settings().get_*()`. No caching — changes take effect on the next command
without reloading BN or the plugin.