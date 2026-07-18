"""Canvas persistence in BN's metadata store (not sidecar files), so a
Canvas travels with the `.bndb` it was built from -- see
docs/adr/0029-node-canvas-architecture.md."""

from __future__ import annotations

from .core.logging import get_logger
from .model import Canvas

logger = get_logger("node_canvas")

_METADATA_KEY = "node_canvas.canvases"


def _load_all(bv) -> dict:
    data = bv.get_metadata(_METADATA_KEY, None)
    return data if isinstance(data, dict) else {}


def list_canvas_names(bv) -> list[str]:
    return sorted(_load_all(bv).keys())


def save_canvas(bv, canvas: Canvas):
    all_canvases = _load_all(bv)
    all_canvases[canvas.name] = canvas.to_dict()
    bv.store_metadata(_METADATA_KEY, all_canvases)
    logger.debug("saved canvas %r (%d nodes, %d edges) for %r", canvas.name, len(canvas.nodes), len(canvas.edges), bv.file.filename)


def load_canvas(bv, name: str) -> Canvas | None:
    all_canvases = _load_all(bv)
    data = all_canvases.get(name)
    if data is None:
        logger.warning("canvas %r not found for %r", name, bv.file.filename)
        return None
    return Canvas.from_dict(data)


def delete_canvas(bv, name: str):
    all_canvases = _load_all(bv)
    if name in all_canvases:
        del all_canvases[name]
        bv.store_metadata(_METADATA_KEY, all_canvases)
        logger.debug("deleted canvas %r for %r", name, bv.file.filename)
