"""Standalone scripts bundled with the plugin -- each also runnable directly
as `python scripts/<name>.py ...` from a shell, and (via this package) also
importable in-process by the plugin itself, e.g. `__init__.py`'s "Install
MCP Clients" GUI command calling `install_mcp_clients.main(argv)` directly
instead of shelling out to a separate interpreter.
"""
