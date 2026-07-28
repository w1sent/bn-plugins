---
name: node-canvas
description: Build or extend a Binary Ninja node-canvas graph (nodes bound to addresses, edges, groups) from a running BN session's execute_script, to visualize analysis results (call trees, xref graphs, custom diagrams) for the user. Also the reference for another plugin author who wants to create/populate a canvas programmatically. Use when asked to draw/visualize/diagram a call graph, xref graph, data-flow sketch, or any other node/edge structure in Binary Ninja, or when node-canvas's `api.py` functions (`create_canvas`, `add_node`, `add_edge`, `add_callers`, `add_callees`, ...) are relevant.
---

`node-canvas` (`ux/node-canvas/`) is a freeform, persisted graph workspace in
Binary Ninja: nodes bound to addresses (or plain custom nodes), edges with
style/routing/arrows, collapsible groups, all stored in the `.bndb`'s
metadata and rendered by a `QGraphicsView` sidebar panel. `api.py` is its
Qt-free scriptable surface — the same thing an agent drives via `binja-mcp`'s
`execute_script`/`create_snippet` tools, and the same thing another plugin
can call into to add its own findings as a graph instead of building a
custom visualization from scratch.

## Reaching the API

BN loads this plugin's directory name — `node-canvas`, with a hyphen — as
its module name, which isn't valid as a plain `import` statement target.
Reach it via `importlib` instead, every time, whether you're a one-off
script or another plugin's code:

```python
import importlib
api = importlib.import_module("node-canvas.api")
```

If you're another plugin reusing node-canvas rather than a one-off script:
per [ADR-0014](../../../../docs/adr/0014-plugins-independent-no-dependencies.md),
plugins have no declared/enforced dependencies on each other yet, so guard
the import and degrade gracefully if node-canvas isn't installed:

```python
try:
    node_canvas_api = importlib.import_module("node-canvas.api")
except ImportError:
    node_canvas_api = None  # feature unavailable; don't hard-fail your own plugin
```

## Model

- **`Canvas`** — a named graph: `nodes: dict[int, Node]`, `edges: dict[int,
  Edge]`, `groups: dict[int, Group]`, plus a legend. One `Canvas` object per
  bv is "live" at a time (the one an open sidebar panel is bound to) —
  `widget.py` observes it and re-renders on every mutation, whether the
  mutation came from the GUI or from your script.
- **`Node`** — `label`, optional `address`, `color`/`border_color`,
  position. If `address` is set and `pinned_label` is `False` (the
  default), the *displayed* label is live-resolved from BN at render time
  (function/data var/symbol name, or falls back to the bare hex address if
  nothing resolves there anymore) — `label` itself is only a fallback/seed,
  not what's shown. Pass **`pinned_label=True`** for a node whose `label`
  you crafted yourself and want shown verbatim regardless of what's at that
  address (e.g. a memory-location node with a hex/string preview baked into
  the label) — otherwise your custom text is silently discarded in favor of
  live resolution the moment `address` is set to anything.
- **`Edge`** — `src`/`dst` (`Node`s), `color`, `thickness`, `arrow_start`/
  `arrow_end`, `style` (`"solid"|"dashed"|"dotted"|"dashdot"` — the drawn
  line pattern), `routing` (`"straight"|"curved"|"orthogonal"|"polyline"` —
  the drawn *path*, independent of style: `curved` bows parallel edges
  apart for readability, `orthogonal`/`polyline` route around any node/group
  box a direct line would otherwise cut through).
- **`Group`** — named, colored, nestable, collapsible container for nodes.

## Canvas lifecycle

```python
api.create_canvas(bv, name) -> Canvas          # new, empty, saved
api.open_canvas(bv, name) -> Canvas | None      # load an existing one
api.list_canvases(bv) -> list[str]
api.save_canvas(bv, canvas)                     # persist after headless mutation
api.delete_canvas(bv, name)
```

Canvases persist in `bv`'s BN metadata store, so they travel with the
`.bndb`. **Making a result visible to the user is a separate step from
building it**, and has two real gotchas:

1. A canvas you `create_canvas` isn't automatically the sidebar's "active"
   canvas. If the sidebar panel isn't open yet, set it explicitly so the
   first open shows your work instead of an unrelated/empty canvas:
   ```python
   persistence = importlib.import_module("node-canvas.persistence")
   persistence.set_active_canvas_name(bv, canvas.name)
   ```
2. If the sidebar panel is **already open**, saving a brand-new canvas name
   does *not* make it pop up as a tab immediately — the tab bar only
   refreshes on specific UI events (switching tabs, opening the panel).
   Tell the user to switch tabs or reopen the panel to see it. If you
   instead want the update to appear live with no user action, mutate the
   canvas the panel is *already showing* — `open_canvas(bv,
   persistence.get_active_canvas_name(bv))` — rather than creating a new
   one, since `widget.py` only observes canvases it already has open, live
   in memory (a freshly-deserialized copy of the same name is a different
   Python object and isn't wired to anything until it's saved and the panel
   reloads it).

## Building a graph

```python
api = importlib.import_module("node-canvas.api")
canvas = api.create_canvas(bv, "malware-chain")

n1 = api.add_node(canvas, "entry", address=bv.entry_point)
n2 = api.add_node(canvas, func.name, address=func.start)
edge = api.add_edge(canvas, n1, n2, style="dashed", routing="curved", arrow_end=True)

api.set_node_color(canvas, n2, "#e63946")
api.set_edge_routing(canvas, edge, "orthogonal")  # dodge intervening node boxes

api.save_canvas(bv, canvas)  # always call this after headless mutation
```

Wrap a batch of inserts in `canvas.batch()` (a context manager on the
`Canvas` object itself, not `api`) when adding many nodes/edges at once —
it coalesces every change into one redraw instead of one per call:

```python
with canvas.batch():
    for func in candidate_functions:
        api.add_node(canvas, func.name, address=func.start)
```

**Auto-populate helpers** build call-tree subgraphs and de-duplicate as they
go — repeat calls (or multiple call sites between the same two functions)
reuse the existing node/edge instead of adding a duplicate:

```python
api.add_callers(bv, canvas, address, depth=2)   # callers, recursively
api.add_callees(bv, canvas, address, depth=2)   # callees, recursively
api.add_call_tree(bv, canvas, address, depth=2) # alias for add_callees
```

These already call `save_canvas` internally and run their own `batch()` —
you don't need to wrap or re-save after calling them.

**Memory-location nodes** (raw byte ranges, not functions/symbols) need
`pinned_label=True` or their crafted preview text gets discarded the moment
`address` is set (see Model above):

```python
data = bv.read(addr, 16)
label = f"{addr:#x}: {data.hex()} [{addr:#x}-{addr + 16:#x}]"
api.add_node(canvas, label, address=addr, pinned_label=True)
```

**Groups and legend:**

```python
group = api.group_nodes(canvas, [n1, n2], "crypto routines", color="#98c1d9")
api.collapse_group(canvas, group)   # hides members behind one box
api.add_legend_entry(canvas, "#e63946", "suspicious")
```

## Export / import

```python
api.export_json(canvas, path)   # full-fidelity, round-trips via import_json
api.export_dot(canvas, path)    # Graphviz DOT, round-trips via import_dot
api.export_mermaid(canvas, path)  # one-way, for pasting into docs/chat
api.export_image(canvas, path, scope="current")  # needs an OPEN widget -- rasterizes the live Qt scene, raises otherwise

api.import_dot(canvas, path)    # merges into an existing canvas, doesn't overwrite
api.import_json(canvas, path)
```

`import_dot`/`import_json` *merge* into the `Canvas` you pass, they don't
replace it or auto-save — call `save_canvas` afterward if nothing has an
open widget observing this canvas.

## Discoverability

`api.help()` returns a live, always-current signature listing generated
from the module itself — call it once at the start of a session instead of
trusting this document's examples to have kept up with every signature:

```python
api = importlib.import_module("node-canvas.api")
print(api.help())
```

## Common workflow: visualize a call graph around a function

```python
import importlib
api = importlib.import_module("node-canvas.api")
persistence = importlib.import_module("node-canvas.persistence")

target = bv.get_functions_by_name("suspicious_func")[0]
canvas = api.create_canvas(bv, "suspicious_func-context")
api.add_callers(bv, canvas, target.start, depth=2)
api.add_callees(bv, canvas, target.start, depth=2)
persistence.set_active_canvas_name(bv, canvas.name)
```

Then tell the user: "open the Node Canvas sidebar panel (its icon in the
right sidebar) to view it" if it isn't already open — per the Canvas
lifecycle gotchas above.

## Pitfalls checklist

- Plain `import node-canvas` / `import node_canvas` — invalid syntax /
  wrong module name. Use `importlib.import_module("node-canvas...")`.
- Setting `address` on a node without `pinned_label=True` when you need
  your own label text shown — it'll be silently replaced by live BN
  resolution (or the bare address, if nothing resolves).
- Forgetting `save_canvas` after headless mutation with no widget open —
  the API doesn't autosave for you; only the GUI's own observer-driven path
  does that.
- Assuming a brand-new canvas name shows up immediately in an
  already-open sidebar panel — it doesn't, until something triggers a tab
  refresh.
- Mutating a freshly-`open_canvas`'d copy expecting it to update an
  already-open panel showing the "same" canvas — they're different Python
  objects unless it's literally the one the widget already loaded.
