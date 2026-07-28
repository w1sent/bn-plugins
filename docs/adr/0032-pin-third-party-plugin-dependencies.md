# Pin third-party dependencies in plugin `requirements.txt`

Each plugin's `requirements.txt` (materialized into `.deps/` per ADR-0002)
should pin third-party packages to a known-good version or range, not leave
them unversioned. An unpinned `mcp` in `ai/mcp-server/requirements.txt` picked
up upstream's `mcp` 2.0.0 the day it shipped, which renamed
`mcp.server.fastmcp.FastMCP` to `mcp.server.mcpserver.MCPServer` and broke
`server.py`/`gui.py` on the next `--link` install/reinstall, with no code
change on our side to explain the crash.

Two things are at stake: stability (a routine reinstall shouldn't silently
swap in a breaking major version) and security (an unpinned dependency
resolves to whatever is newest at install time, including anything newly
published, malicious or not, under that name). Pinning trades a small amount
of staleness for install reproducibility and a deliberate upgrade point.

Applied: `ai/mcp-server/requirements.txt` now reads `mcp<2.0`. Going forward,
new third-party entries in any plugin's `requirements.txt` should specify at
least an upper bound; see ADR-0033 for how upgrades past a pin get decided.
