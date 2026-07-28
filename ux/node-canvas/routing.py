"""Qt-free edge-path routing (docs/adr/0029 -- Qt stays confined to
widget.py). Given two already-clipped endpoint points and the rects of
every other node/group box currently on screen, compute a waypoint list an
edge should route through instead of a direct line.

"straight" and "curved" need none of this -- they're a direct line/bezier
computed by widget.py itself from each item's own geometry. This module
handles "orthogonal" and "polyline", both of which detect an obstacle box
sitting between the endpoints and route around it. It's a practical
single/few-obstacle detour, not a general graph pathfinder: if no clean
detour is found within a small, bounded number of tries, these fall back
to the direct/simple path rather than guaranteeing an obstacle-free route
for every possible layout.
"""

from __future__ import annotations

import math

Point = tuple[float, float]
Rect = tuple[float, float, float, float]  # x, y, w, h

_MARGIN = 8.0  # clearance kept between a routed path and an obstacle's edge


def _segment_intersects_rect(p1: Point, p2: Point, rect: Rect) -> bool:
    """Liang-Barsky segment/AABB intersection test."""
    rx, ry, rw, rh = rect
    xmin, xmax = rx, rx + rw
    ymin, ymax = ry, ry + rh
    x1, y1 = p1
    x2, y2 = p2
    dx, dy = x2 - x1, y2 - y1

    t0, t1 = 0.0, 1.0
    for p, q in ((-dx, x1 - xmin), (dx, xmax - x1), (-dy, y1 - ymin), (dy, ymax - y1)):
        if p == 0:
            if q < 0:
                return False
            continue
        r = q / p
        if p < 0:
            if r > t1:
                return False
            if r > t0:
                t0 = r
        else:
            if r < t0:
                return False
            if r < t1:
                t1 = r
    return t0 <= t1


def _path_intersects_any(points: list[Point], obstacles: list[Rect]) -> bool:
    return any(
        _segment_intersects_rect(points[i], points[i + 1], rect)
        for i in range(len(points) - 1)
        for rect in obstacles
    )


def _blocking_rect(points: list[Point], obstacles: list[Rect]) -> Rect | None:
    for i in range(len(points) - 1):
        for rect in obstacles:
            if _segment_intersects_rect(points[i], points[i + 1], rect):
                return rect
    return None


def _expand(rect: Rect, margin: float) -> Rect:
    x, y, w, h = rect
    return (x - margin, y - margin, w + 2 * margin, h + 2 * margin)


def orthogonal_path(src: Point, dst: Point, obstacles: list[Rect]) -> list[Point]:
    """Manhattan (horizontal/vertical-only) waypoints from `src` to `dst`,
    dodging `obstacles` -- rects for every OTHER node/group box currently
    on screen (never src's or dst's own)."""
    candidates = [
        [src, (dst[0], src[1]), dst],
        [src, (src[0], dst[1]), dst],
    ]
    for path in candidates:
        if not _path_intersects_any(path, obstacles):
            return path

    # Both simple L-paths hit something -- go around whichever obstacle
    # blocks the first candidate, via its expanded top/bottom or left/right
    # edge, then re-check.
    blocker = _blocking_rect(candidates[0], obstacles)
    if blocker is None:
        return candidates[0]
    bx, by, bw, bh = _expand(blocker, _MARGIN)
    for detour_y in (by, by + bh):
        path = [src, (src[0], detour_y), (dst[0], detour_y), dst]
        if not _path_intersects_any(path, obstacles):
            return path
    for detour_x in (bx, bx + bw):
        path = [src, (detour_x, src[1]), (detour_x, dst[1]), dst]
        if not _path_intersects_any(path, obstacles):
            return path

    return candidates[0]  # best effort -- see module docstring


def polyline_path(src: Point, dst: Point, obstacles: list[Rect]) -> list[Point]:
    """Like orthogonal_path, but detours via a diagonal cut past just the
    blocking obstacle's nearest corner instead of a full right-angle
    detour -- fewer bends, shorter route."""
    direct = [src, dst]
    if not _path_intersects_any(direct, obstacles):
        return direct

    blocker = _blocking_rect(direct, obstacles)
    if blocker is None:
        return direct
    bx, by, bw, bh = _expand(blocker, _MARGIN)
    corners = [(bx, by), (bx + bw, by), (bx, by + bh), (bx + bw, by + bh)]

    def path_length(pts: list[Point]) -> float:
        return sum(math.dist(pts[i], pts[i + 1]) for i in range(len(pts) - 1))

    best = None
    for corner in corners:
        path = [src, corner, dst]
        if not _path_intersects_any(path, obstacles) and (best is None or path_length(path) < path_length(best)):
            best = path
    if best is not None:
        return best

    # A single corner didn't clear it (rare) -- try adjacent corner pairs
    # on the same side as a small bounded detour before giving up.
    for c1, c2 in ((corners[0], corners[2]), (corners[1], corners[3]), (corners[0], corners[1]), (corners[2], corners[3])):
        path = [src, c1, c2, dst]
        if not _path_intersects_any(path, obstacles):
            return path

    return direct  # best effort -- see module docstring
