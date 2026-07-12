"""Scheduling-order strategies for bulk rename operations.

Every function here is duck-typed against a minimal function-like interface:
``.start`` (int), ``.name`` (str), ``.callers`` (iterable of function-like),
``.callees`` (iterable of function-like). Type hints reference
``binaryninja.function.Function`` for documentation only -- nothing in this
module imports ``binaryninja``, so it can be unit- and fuzz-tested with
plain Python fakes outside Binary Ninja.

BN-specific concepts (the entry function, exported symbols) are resolved by
the caller into plain ``roots`` lists before reaching this module -- see
``api._resolve_roots``.
"""

from __future__ import annotations

from collections import deque
from typing import TYPE_CHECKING, Callable, Iterable, List, Optional, Sequence

if TYPE_CHECKING:
    from binaryninja.function import Function

ORDERINGS = (
    "default",
    "leaves-first",
    "top-down",
    "local-breadth",
    "local-bottom-up",
    "local-up",
    "export-down",
    "info-gain",
)

# Orderings whose benefit (renaming a callee/deeper node before the function
# that depends on it) requires *completion* order, not just submission order.
# Used by the concurrency layer to decide whether to warn under fixed-pool.
PROPAGATION_DEPENDENT = frozenset({"leaves-first", "local-bottom-up", "info-gain"})

# Orderings that require an explicit anchor function.
NEEDS_ANCHOR = frozenset({"local-breadth", "local-bottom-up", "local-up"})

# Orderings that require a caller-resolved `roots` list.
NEEDS_ROOTS = frozenset({"top-down", "export-down"})


class OrderingError(ValueError):
    """Raised when an ordering strategy is requested without its required inputs."""


def zero_caller_roots(universe: Sequence["Function"]) -> List["Function"]:
    """Fallback root set: functions in `universe` with no callers."""
    return [f for f in universe if not list(f.callers)]


def order_functions(
    funcs: Iterable["Function"],
    ordering: str = "default",
    *,
    anchor: Optional["Function"] = None,
    roots: Optional[Sequence["Function"]] = None,
    restrict_to: Optional[Iterable["Function"]] = None,
) -> List["Function"]:
    """Return `funcs` reordered according to `ordering`.

    `anchor` is required for local-* orderings. `roots` is required for
    top-down/export-down (already resolved by the caller from `bv`).
    `restrict_to`, if given, confines graph traversal to that set of
    functions (by start address) -- members of `funcs` unreachable within
    that restriction sort last, address-ascending.
    """
    funcs = list(funcs)
    ordering = ordering or "default"

    if ordering == "default":
        return funcs

    if ordering not in ORDERINGS:
        raise OrderingError(f"unknown ordering '{ordering}'")

    if ordering in NEEDS_ANCHOR and anchor is None:
        raise OrderingError(f"ordering '{ordering}' requires an anchor function")

    if ordering in NEEDS_ROOTS and not roots:
        raise OrderingError(f"ordering '{ordering}' requires roots")

    if ordering == "leaves-first":
        return _sort_by_count(funcs, key=lambda f: len(list(f.callees)))

    if ordering == "info-gain":
        return _sort_by_count(funcs, key=lambda f: len(list(f.callers)), reverse=True)

    if ordering == "top-down":
        return _root_major_bfs(roots, funcs, neighbors=lambda f: f.callees)

    if ordering == "export-down":
        return _root_major_bfs(roots, funcs, neighbors=lambda f: f.callees)

    if ordering == "local-breadth":
        return _bfs_restricted(anchor, funcs, neighbors=lambda f: f.callees, restrict_to=restrict_to)

    if ordering == "local-up":
        return _bfs_restricted(anchor, funcs, neighbors=lambda f: f.callers, restrict_to=restrict_to)

    if ordering == "local-bottom-up":
        order = _bfs_restricted(anchor, funcs, neighbors=lambda f: f.callees, restrict_to=restrict_to)
        return list(reversed(order))

    raise OrderingError(f"unhandled ordering '{ordering}'")


def _sort_by_count(
    funcs: List["Function"], key: Callable[["Function"], int], reverse: bool = False
) -> List["Function"]:
    return sorted(funcs, key=lambda f: (-key(f) if reverse else key(f), f.start))


def _root_major_bfs(
    roots: Sequence["Function"],
    funcs: List["Function"],
    neighbors: Callable[["Function"], Iterable["Function"]],
) -> List["Function"]:
    target_addrs = {f.start for f in funcs}
    seen = set()
    added = set()
    visited_order: List["Function"] = []

    for root in sorted(roots, key=lambda f: f.start):
        if root.start in seen:
            continue
        queue = deque([root])
        seen.add(root.start)
        while queue:
            cur = queue.popleft()
            if cur.start in target_addrs and cur.start not in added:
                visited_order.append(cur)
                added.add(cur.start)
            for nb in neighbors(cur):
                if nb.start in seen:
                    continue
                seen.add(nb.start)
                queue.append(nb)

    remainder = sorted((f for f in funcs if f.start not in added), key=lambda f: f.start)
    return visited_order + remainder


def _bfs_restricted(
    anchor: "Function",
    funcs: List["Function"],
    neighbors: Callable[["Function"], Iterable["Function"]],
    restrict_to: Optional[Iterable["Function"]] = None,
) -> List["Function"]:
    target_addrs = {f.start for f in funcs}
    universe_addrs = None
    if restrict_to is not None:
        universe_addrs = {f.start for f in restrict_to}

    added = set()
    visited_order: List["Function"] = []
    seen = {anchor.start}
    queue = deque([anchor])

    while queue:
        cur = queue.popleft()
        if cur.start in target_addrs and cur.start not in added:
            visited_order.append(cur)
            added.add(cur.start)
        for nb in neighbors(cur):
            if nb.start in seen:
                continue
            if universe_addrs is not None and nb.start not in universe_addrs:
                continue
            seen.add(nb.start)
            queue.append(nb)

    remainder = sorted((f for f in funcs if f.start not in added), key=lambda f: f.start)
    return visited_order + remainder
