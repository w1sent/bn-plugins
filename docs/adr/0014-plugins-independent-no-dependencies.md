# Plugins are independent — no inter-plugin dependencies

Plugins operate on the Binary Ninja database in isolation with no declared
dependencies on other plugins. If a dependency emerges later (e.g. a
type-reconstruct plugin that needs structs from suggest-structs), an
`x_plugin_dependencies` field will be added to `plugin.json` at that point.
Adding dependency management now is complexity without a use case.