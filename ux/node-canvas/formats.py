"""Import/export formats for node-canvas, per docs/adr/0029 and
CONTEXT.md's node-canvas glossary:

- JSON: native format, full round-trip (import/export).
- DOT (Graphviz): full round-trip (import/export). Our own `export_dot`
  output always re-imports cleanly via `import_dot`; arbitrary external
  DOT files are supported on a best-effort basis for the common subset
  (digraph/subgraph, node/edge statements, label/color/penwidth attrs) --
  not the full DOT grammar.
- Mermaid: export-only, structural (nodes/labels/edges, groups as
  `subgraph`), no color/thickness styling, always the full canvas.

Image export (PNG/PDF) needs a live QGraphicsScene to rasterize, so it
lives in widget.py, not here -- this module stays Qt-free per ADR-0029.
"""

from __future__ import annotations

import json
import re

from .core.logging import get_logger
from .model import DEFAULT_EDGE_ROUTING, DEFAULT_EDGE_STYLE, DEFAULT_EDGE_THICKNESS, EDGE_ROUTINGS, EDGE_STYLES, Canvas

logger = get_logger("node_canvas")


# -- JSON -------------------------------------------------------------


def export_json(canvas: Canvas, path: str):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(canvas.to_dict(), f, indent=2)
    logger.debug("wrote JSON export of canvas %r to %r", canvas.name, path)


def import_json(path: str) -> Canvas:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    canvas = Canvas.from_dict(data)
    logger.debug("read JSON canvas %r from %r (%d nodes)", canvas.name, path, len(canvas.nodes))
    return canvas


# -- Mermaid (export-only) --------------------------------------------


def _mermaid_id(prefix, node_id):
    return f"{prefix}{node_id}"


def _mermaid_escape(label: str) -> str:
    return label.replace('"', "'")


def export_mermaid(canvas: Canvas, path: str):
    lines = ["flowchart TD"]

    def emit_group(group, indent):
        pad = "    " * indent
        lines.append(f'{pad}subgraph {_mermaid_id("g", group.id)} ["{_mermaid_escape(group.name)}"]')
        for child in group.child_groups:
            emit_group(child, indent + 1)
        for node in group.member_nodes:
            lines.append(f'{"    " * (indent + 1)}{_mermaid_id("n", node.id)}["{_mermaid_escape(node.label)}"]')
        lines.append(f"{pad}end")

    top_groups = [g for g in canvas.groups.values() if g.parent is None]
    for group in top_groups:
        emit_group(group, 1)

    for node in canvas.nodes.values():
        if node.group is None:
            lines.append(f'    {_mermaid_id("n", node.id)}["{_mermaid_escape(node.label)}"]')

    for edge in canvas.edges.values():
        if edge.arrow_start and edge.arrow_end:
            arrow = "<-->"
        elif edge.arrow_start:
            arrow = "<--"
        elif edge.arrow_end:
            arrow = "-->"
        else:
            arrow = "---"
        lines.append(f'    {_mermaid_id("n", edge.src.id)} {arrow} {_mermaid_id("n", edge.dst.id)}')

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    logger.debug("wrote Mermaid export of canvas %r to %r", canvas.name, path)


# -- DOT (round-trip) ---------------------------------------------------


def _dot_escape(value: str) -> str:
    return str(value).replace('"', '\\"')


def export_dot(canvas: Canvas, path: str):
    lines = [f'digraph "{_dot_escape(canvas.name)}" {{']

    def emit_group(group, indent):
        pad = "    " * indent
        lines.append(f'{pad}subgraph "cluster_{group.id}" {{')
        lines.append(f'{pad}    label="{_dot_escape(group.name)}";')
        if group.color:
            lines.append(f'{pad}    color="{_dot_escape(group.color)}";')
        for node in group.member_nodes:
            lines.append(f'{pad}    n{node.id} {_node_attrs(node)};')
        for child in group.child_groups:
            emit_group(child, indent + 1)
        lines.append(f"{pad}}}")

    def _node_attrs(node):
        attrs = [f'label="{_dot_escape(node.label)}"']
        if node.color:
            attrs.append(f'color="{_dot_escape(node.color)}"')
        if node.address is not None:
            attrs.append(f'address="{node.address:#x}"')
        if node.pinned_label:
            attrs.append('pinned_label="true"')
        attrs.append(f"pos=\"{node.x / 100.0},{node.y / 100.0}!\"")
        return "[" + ", ".join(attrs) + "]"

    top_groups = [g for g in canvas.groups.values() if g.parent is None]
    for group in top_groups:
        emit_group(group, 1)

    for node in canvas.nodes.values():
        if node.group is None:
            lines.append(f"    n{node.id} {_node_attrs(node)};")

    for edge in canvas.edges.values():
        attrs = []
        if edge.color:
            attrs.append(f'color="{_dot_escape(edge.color)}"')
        attrs.append(f"penwidth={edge.thickness}")
        if edge.style != DEFAULT_EDGE_STYLE:
            attrs.append(f'style="{edge.style}"')
        if edge.routing != DEFAULT_EDGE_ROUTING:
            attrs.append(f'routing="{edge.routing}"')
        if edge.arrow_start and edge.arrow_end:
            attrs.append('dir="both"')
        elif edge.arrow_start and not edge.arrow_end:
            attrs.append('dir="back"')
        elif not edge.arrow_start and not edge.arrow_end:
            attrs.append('dir="none"')
        # arrow_end-only is DOT's implicit default ("forward") -- omitted.
        lines.append(f"    n{edge.src.id} -> n{edge.dst.id} [{', '.join(attrs)}];")

    lines.append("}")

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    logger.debug("wrote DOT export of canvas %r to %r", canvas.name, path)


def _strip_comments(text: str) -> str:
    text = re.sub(r"//[^\n]*", "", text)
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return text


def _split_statements(body: str) -> list[str]:
    """Split DOT source into a flat stream of statement strings plus the
    structural tokens '{' and '}', splitting on ';'/newline/braces while
    ignoring anything inside quotes or a [...] attribute list."""
    tokens = []
    current = []
    in_quotes = False
    bracket_depth = 0

    for ch in body:
        if ch == '"':
            in_quotes = not in_quotes
            current.append(ch)
            continue
        if in_quotes:
            current.append(ch)
            continue
        if ch == "[":
            bracket_depth += 1
            current.append(ch)
            continue
        if ch == "]":
            bracket_depth -= 1
            current.append(ch)
            continue
        if bracket_depth == 0 and ch in "{};":
            token = "".join(current).strip()
            if token:
                tokens.append(token)
            if ch in "{}":
                tokens.append(ch)
            current = []
            continue
        if bracket_depth == 0 and ch == "\n":
            token = "".join(current).strip()
            if token:
                tokens.append(token)
            current = []
            continue
        current.append(ch)

    trailing = "".join(current).strip()
    if trailing:
        tokens.append(trailing)
    return tokens


_ATTR_LIST_RE = re.compile(r"\[(.*)\]\s*$", re.S)
_ATTR_PAIR_RE = re.compile(r'(\w+)\s*=\s*(".*?"|[\w.#!,-]+)')
_EDGE_RE = re.compile(r'^"?([\w.]+)"?\s*(->|--)\s*"?([\w.]+)"?\s*(\[.*\])?$', re.S)
_SUBGRAPH_HEADER_RE = re.compile(r"^subgraph\s+\"?([\w.]+)\"?$", re.I)
_GRAPH_HEADER_RE = re.compile(r"^(strict\s+)?(di)?graph\s+\"?([\w.]*)\"?$", re.I)


def _parse_attrs(attr_str: str) -> dict:
    attrs = {}
    for match in _ATTR_PAIR_RE.finditer(attr_str):
        key, value = match.group(1), match.group(2)
        if value.startswith('"') and value.endswith('"'):
            value = value[1:-1]
        attrs[key.lower()] = value
    return attrs


class _GroupScope:
    def __init__(self, group=None):
        self.group = group  # None means top-level canvas scope


def import_dot(path: str, name: str | None = None) -> Canvas:
    with open(path, encoding="utf-8") as f:
        raw = f.read()
    raw = _strip_comments(raw)
    tokens = _split_statements(raw)

    canvas = Canvas(name or "imported")

    node_by_dot_name: dict[str, "model.Node"] = {}
    scope_stack: list[_GroupScope] = [_GroupScope(None)]
    pending_header = None  # subgraph name awaiting its '{'

    for token in tokens:
        if token == "{":
            group = None
            if pending_header:
                group = canvas.group_nodes([], pending_header, parent=scope_stack[-1].group)
            scope_stack.append(_GroupScope(group))
            pending_header = None
            continue
        if token == "}":
            if len(scope_stack) > 1:
                scope_stack.pop()
            continue

        header_match = _SUBGRAPH_HEADER_RE.match(token)
        if header_match:
            pending_header = header_match.group(1)
            continue
        if _GRAPH_HEADER_RE.match(token):
            graph_name = _GRAPH_HEADER_RE.match(token).group(3)
            if graph_name and name is None:
                canvas.name = graph_name
            continue

        low = token.lower()
        if low.startswith("label=") or low.startswith("color=") or low in ("rankdir", ""):
            attrs = _parse_attrs("[" + token + "]") if "=" in token else {}
            current_group = scope_stack[-1].group
            if current_group is not None:
                if "label" in attrs:
                    current_group.name = attrs["label"]
                if "color" in attrs:
                    current_group.color = attrs["color"]
            continue

        edge_match = _EDGE_RE.match(token)
        if edge_match:
            src_name, _, dst_name, attr_blob = edge_match.groups()
            attrs = _parse_attrs(attr_blob) if attr_blob else {}
            if src_name not in node_by_dot_name:
                node_by_dot_name[src_name] = canvas.add_node(src_name)
            if dst_name not in node_by_dot_name:
                node_by_dot_name[dst_name] = canvas.add_node(dst_name)
            src = node_by_dot_name[src_name]
            dst = node_by_dot_name[dst_name]
            thickness = float(attrs.get("penwidth", DEFAULT_EDGE_THICKNESS))
            dir_attr = attrs.get("dir", "forward").lower()
            if dir_attr == "both":
                arrow_start, arrow_end = True, True
            elif dir_attr == "back":
                arrow_start, arrow_end = True, False
            elif dir_attr == "none":
                arrow_start, arrow_end = False, False
            else:
                arrow_start, arrow_end = False, True
            style = attrs.get("style", DEFAULT_EDGE_STYLE)
            if style not in EDGE_STYLES:
                style = DEFAULT_EDGE_STYLE
            routing = attrs.get("routing", DEFAULT_EDGE_ROUTING)
            if routing not in EDGE_ROUTINGS:
                routing = DEFAULT_EDGE_ROUTING
            canvas.add_edge(src, dst, color=attrs.get("color"), thickness=thickness, arrow_start=arrow_start, arrow_end=arrow_end, style=style, routing=routing)
            continue

        attr_list_match = _ATTR_LIST_RE.search(token)
        node_name = token[: attr_list_match.start()].strip() if attr_list_match else token.strip()
        node_name = node_name.strip('"')
        if not node_name:
            continue
        attrs = _parse_attrs(attr_list_match.group(1)) if attr_list_match else {}

        label = attrs.get("label", node_name)
        color = attrs.get("color")
        address = None
        if "address" in attrs:
            try:
                address = int(attrs["address"], 16) if attrs["address"].startswith("0x") else int(attrs["address"])
            except ValueError:
                address = None
        x, y = 0.0, 0.0
        if "pos" in attrs:
            pos_val = attrs["pos"].rstrip("!")
            try:
                px, py = pos_val.split(",")
                x, y = float(px) * 100.0, float(py) * 100.0
            except ValueError:
                pass

        pinned_label = attrs.get("pinned_label", "").lower() == "true"

        if node_name in node_by_dot_name:
            node = node_by_dot_name[node_name]
            node.label = label
            node.pinned_label = pinned_label
        else:
            node = canvas.add_node(label, address=address, color=color, x=x, y=y, pinned_label=pinned_label)
            node_by_dot_name[node_name] = node

        current_group = scope_stack[-1].group
        if current_group is not None and node.group is None:
            node.group = current_group
            current_group.member_nodes.append(node)

    logger.debug("read DOT canvas %r from %r (%d nodes)", canvas.name, path, len(canvas.nodes))
    return canvas
