# API error handling: follow BN's hybrid exception/None convention

The plugin API follows Binary Ninja's own error handling conventions:
- Custom exceptions (`PluginError`, `AITimeoutError`, `AIConfigError`) for
  hard failures
- `None` return for "not found" queries
- Standard Python exceptions (`ValueError`, `KeyError`) where they
  semantically fit
- `PluginCommand` wrappers catch all exceptions and log user-friendly
  messages

This matches BN's pattern: `ProjectException` for project failures, `None`
from `get_data_var_at()` for missing data, `KeyError` for missing symbols.