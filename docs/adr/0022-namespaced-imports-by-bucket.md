# Namespaced imports by bucket

Plugins are installed preserving their bucket structure:
`BN_PLUGIN_DIR/ai/auto_rename/`, `BN_PLUGIN_DIR/frameworks/flutter/`, etc.
Users import as `from ai.auto_rename import api` — the bucket acts as a
namespace, matching the monorepo layout and preventing name collisions with
other Python packages.