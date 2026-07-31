"""Shared output shaping for read/list tools: filtering, pagination, field
projection, and the plain-text-by-default rendering every one of them
shares (see ADR-0038).

Text is the only thing a normal MCP client ever sees (`content`): a header
line followed by one tab-separated record per line, no alignment padding
(padding is pure token cost for an LLM reader, unlike a human terminal).
JSON only ever travels via `structuredContent`, which a plain MCP client
ignores and the `bn` CLI reads directly for `--format json` -- it is never
a tool input parameter, so ordinary MCP callers never have to think about
it (see ADR-0038's "Output format" section).

`filter_rows`/`project`/`paginate` are plain list-of-dict helpers with no
BN dependency, split out so they're unit-testable without a running BN
(see tests/test_rendering.py). Only `tool_result`/`_target_marker` touch
BN's API, for the optional target-binary marker line.
"""

import re
from typing import Optional

from mcp.types import CallToolResult, TextContent


def filter_rows(rows: list, name_regex: Optional[str], key: str) -> list:
    """Keep rows whose `key` field matches `name_regex` -- substring
    (case-insensitive) if it doesn't compile as a regex, a real regex
    search if it does. Same matching semantics as today's `search()` tool.
    A falsy `name_regex` is a no-op (all rows kept)."""
    if not name_regex:
        return rows
    try:
        regex = re.compile(name_regex, re.IGNORECASE)
    except re.error:
        regex = None

    def matches(row) -> bool:
        text = row.get(key) or ""
        if regex:
            return bool(regex.search(text))
        return name_regex.lower() in text.lower()

    return [r for r in rows if matches(r)]


def project(rows: list, fields: Optional[list]) -> list:
    """Keep only the given field names in each row, in the given order. A
    falsy `fields` is a no-op (every field kept, in each row's own order)."""
    if not fields:
        return rows
    return [{f: r.get(f) for f in fields} for r in rows]


def paginate(rows: list, limit: int, offset: int) -> list:
    return rows[offset : offset + limit]


def _cell(value) -> str:
    if value is None:
        return ""
    return str(value)


def render_table(rows: list, fields: Optional[list] = None) -> str:
    """Render rows as one header line + one tab-separated record per line.
    Column order follows the first row's keys unless `fields` narrows/
    reorders them. Returns a literal "(no results)" for an empty list --
    an empty string reads as "something broke", not "zero matches"."""
    if not rows:
        return "(no results)"
    keys = fields if fields else list(rows[0].keys())
    lines = ["\t".join(keys)]
    for row in rows:
        lines.append("\t".join(_cell(row.get(k)) for k in keys))
    return "\n".join(lines)


def render_kv(pairs: dict) -> str:
    """Render a single record as `key: value` lines -- for single-target
    lookups (get_data, a function's own metadata, ...) rather than
    listings, where a table with one row would be an odd fit."""
    return "\n".join(f"{k}: {_cell(v)}" for k, v in pairs.items())


def _target_marker() -> Optional[dict]:
    """Return {"index", "path"} for whichever binary the current call just
    operated on, or None if the marker is disabled or nothing's resolvable
    (e.g. no binary open). Imports are local to avoid a hard import-time
    dependency between this module and BN/binary_context for callers that
    only want the BN-independent helpers above (see tests/test_rendering.py)."""
    from binaryninja import Settings

    from . import binary_context

    if not Settings().get_bool("mcp_server.echo_target_enabled"):
        return None
    try:
        bv = binary_context.get_current_view()
    except Exception:
        return None
    for i, (view, path) in enumerate(binary_context.list_available_views()):
        if view is bv:
            return {"index": i, "path": path}
    return None


def tool_result(text: str, structured: Optional[dict] = None) -> CallToolResult:
    """Build a tool's return value: `text` as-is for `content` (every MCP
    client sees exactly this, verbatim -- see module docstring), plus
    `structured` (if given) as `structuredContent` for the `bn` CLI's
    `--format json`.

    When enabled (`mcp_server.echo_target_enabled`, default on), prepends a
    single `#binary\tindex\tpath` line identifying which binary this call
    resolved to and ran against. It's still useful context inside `content`
    for a plain MCP client with no separate stderr channel -- "which binary
    did this touch" is exactly the ambiguity ADR-0038 calls out for
    multi-binary sessions. The `bn` CLI additionally knows to peel exactly
    this leading `#`-prefixed line off into its own stderr, so piping
    `content`'s remaining table through `jq`/`grep` stays clean."""
    marker = _target_marker()
    final_text = text
    final_structured = dict(structured) if structured is not None else None
    if marker is not None:
        final_text = f"#binary\t{marker['index']}\t{marker['path']}\n{text}"
        if final_structured is not None:
            final_structured["target"] = marker
    if final_structured is None:
        return CallToolResult(content=[TextContent(type="text", text=final_text)])
    return CallToolResult(
        content=[TextContent(type="text", text=final_text)],
        structuredContent=final_structured,
    )
