# BN's native `plugin.json` with `x_min_core_version`

Plugins use Binary Ninja's native `plugin.json` manifest format for version,
author, description, dependencies, and minimum BN version. A single custom
field `x_min_core_version` is added so the installer can validate that the
vendored `core/` version satisfies the plugin's requirement at install time.
The `x_` prefix marks it as a custom extension, avoiding collisions with
future BN manifest fields.