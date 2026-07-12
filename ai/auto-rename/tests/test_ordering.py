"""Unit + fuzz tests for ordering.py.

Runs outside Binary Ninja: `ordering.py` is duck-typed, so a minimal fake
function object (start/name/callers/callees) stands in for
`binaryninja.function.Function`. See ai/auto-rename/tests/run.py for the
BN integration test against real binaries (per ADR 0009); it requires
`testcases/` infrastructure this repo doesn't have yet for any plugin.
"""

import random
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ordering import (  # noqa: E402
    OrderingError,
    order_functions,
    zero_caller_roots,
)


class FakeFunc:
    def __init__(self, name, start):
        self.name = name
        self.start = start
        self.callers = []
        self.callees = []

    def __repr__(self):
        return f"<FakeFunc {self.name} {self.start:#x}>"


def link(caller, callee):
    caller.callees.append(callee)
    callee.callers.append(caller)


def make_chain(n, start=0x1000, step=0x10):
    """f0 -> f1 -> f2 -> ... -> f(n-1) (fN calls fN+1)."""
    funcs = [FakeFunc(f"sub_{i}", start + i * step) for i in range(n)]
    for i in range(n - 1):
        link(funcs[i], funcs[i + 1])
    return funcs


def names(funcs):
    return [f.name for f in funcs]


def test_default_ordering_is_identity():
    funcs = make_chain(4)
    assert order_functions(funcs, "default") == funcs
    assert order_functions(funcs) == funcs


def test_unknown_ordering_raises():
    funcs = make_chain(2)
    with pytest.raises(OrderingError):
        order_functions(funcs, "bogus")


def test_local_orderings_require_anchor():
    funcs = make_chain(2)
    for strategy in ("local-breadth", "local-bottom-up", "local-up"):
        with pytest.raises(OrderingError):
            order_functions(funcs, strategy)


def test_root_orderings_require_roots():
    funcs = make_chain(2)
    for strategy in ("top-down", "export-down"):
        with pytest.raises(OrderingError):
            order_functions(funcs, strategy)


def test_leaves_first_sorts_by_callee_count_ascending():
    leaf = FakeFunc("leaf", 0x100)
    mid = FakeFunc("mid", 0x200)
    hub = FakeFunc("hub", 0x300)
    link(hub, leaf)
    link(hub, mid)
    link(mid, leaf)
    # leaf: 0 callees, mid: 1 callee, hub: 2 callees
    funcs = [hub, leaf, mid]
    result = order_functions(funcs, "leaves-first")
    assert names(result) == ["leaf", "mid", "hub"]


def test_leaves_first_ties_break_by_address_ascending():
    a = FakeFunc("a", 0x300)
    b = FakeFunc("b", 0x100)
    c = FakeFunc("c", 0x200)
    # all zero callees -> tie, break by address
    result = order_functions([a, b, c], "leaves-first")
    assert names(result) == ["b", "c", "a"]


def test_info_gain_sorts_by_fanin_descending():
    popular = FakeFunc("popular", 0x100)
    lonely = FakeFunc("lonely", 0x200)
    caller1 = FakeFunc("caller1", 0x300)
    caller2 = FakeFunc("caller2", 0x400)
    link(caller1, popular)
    link(caller2, popular)
    funcs = [lonely, popular]
    result = order_functions(funcs, "info-gain")
    assert names(result) == ["popular", "lonely"]


def test_info_gain_ties_break_by_address_ascending():
    a = FakeFunc("a", 0x300)
    b = FakeFunc("b", 0x100)
    result = order_functions([a, b], "info-gain")
    assert names(result) == ["b", "a"]


def test_local_breadth_bfs_from_anchor_through_callees():
    anchor = FakeFunc("anchor", 0x100)
    child1 = FakeFunc("child1", 0x200)
    child2 = FakeFunc("child2", 0x300)
    grandchild = FakeFunc("grandchild", 0x400)
    link(anchor, child1)
    link(anchor, child2)
    link(child1, grandchild)
    funcs = [grandchild, child2, child1, anchor]
    result = order_functions(funcs, "local-breadth", anchor=anchor)
    assert names(result) == ["anchor", "child1", "child2", "grandchild"]


def test_local_bottom_up_is_reverse_of_breadth_order():
    anchor = FakeFunc("anchor", 0x100)
    child = FakeFunc("child", 0x200)
    grandchild = FakeFunc("grandchild", 0x300)
    link(anchor, child)
    link(child, grandchild)
    funcs = [anchor, child, grandchild]
    result = order_functions(funcs, "local-bottom-up", anchor=anchor)
    assert names(result) == ["grandchild", "child", "anchor"]


def test_local_up_bfs_from_anchor_through_callers_closest_first():
    anchor = FakeFunc("anchor", 0x100)
    direct_caller = FakeFunc("direct_caller", 0x200)
    far_caller = FakeFunc("far_caller", 0x300)
    link(direct_caller, anchor)
    link(far_caller, direct_caller)
    funcs = [far_caller, direct_caller, anchor]
    result = order_functions(funcs, "local-up", anchor=anchor)
    assert names(result) == ["anchor", "direct_caller", "far_caller"]


def test_local_breadth_anchor_not_in_funcs_is_seed_only():
    anchor = FakeFunc("anchor", 0x100)
    child = FakeFunc("child", 0x200)
    link(anchor, child)
    # anchor itself is not part of the to-rename set
    result = order_functions([child], "local-breadth", anchor=anchor)
    assert names(result) == ["child"]


def test_local_breadth_restrict_to_confines_traversal():
    anchor = FakeFunc("anchor", 0x100)
    inside = FakeFunc("inside", 0x200)
    gate = FakeFunc("gate", 0x300)  # not in restrict_to: blocks traversal through it
    outside = FakeFunc("outside", 0x400)
    link(anchor, inside)
    link(anchor, gate)
    link(gate, outside)
    funcs = [inside, gate, outside]
    result = order_functions(
        funcs, "local-breadth", anchor=anchor, restrict_to=[anchor, inside, gate]
    )
    # outside is unreachable within the restricted universe -> sorts last
    assert names(result) == ["inside", "gate", "outside"]


def test_unreachable_members_sort_last_by_address():
    anchor = FakeFunc("anchor", 0x100)
    reachable = FakeFunc("reachable", 0x200)
    unreachable_b = FakeFunc("unreachable_b", 0x400)
    unreachable_a = FakeFunc("unreachable_a", 0x300)
    link(anchor, reachable)
    funcs = [unreachable_b, reachable, unreachable_a]
    result = order_functions(funcs, "local-breadth", anchor=anchor)
    assert names(result) == ["reachable", "unreachable_a", "unreachable_b"]


def test_root_major_bfs_first_touch_wins_across_roots():
    root_a = FakeFunc("root_a", 0x100)
    root_b = FakeFunc("root_b", 0x200)
    shared = FakeFunc("shared", 0x300)
    only_b = FakeFunc("only_b", 0x400)
    link(root_a, shared)
    link(root_b, shared)
    link(root_b, only_b)
    funcs = [only_b, shared]
    # root_a explored fully (first, by address) before root_b -> shared
    # attributed to root_a's traversal, not re-visited under root_b.
    result = order_functions(funcs, "top-down", roots=[root_b, root_a])
    assert names(result) == ["shared", "only_b"]


def test_export_down_uses_provided_roots():
    export1 = FakeFunc("export1", 0x100)
    export2 = FakeFunc("export2", 0x200)
    callee = FakeFunc("callee", 0x300)
    link(export2, callee)
    funcs = [callee, export1, export2]
    result = order_functions(funcs, "export-down", roots=[export1, export2])
    assert names(result) == ["export1", "export2", "callee"]


def test_cycles_do_not_infinite_loop_and_visit_once():
    a = FakeFunc("a", 0x100)
    b = FakeFunc("b", 0x200)
    c = FakeFunc("c", 0x300)
    link(a, b)
    link(b, c)
    link(c, a)  # cycle back to a
    funcs = [a, b, c]
    result = order_functions(funcs, "local-breadth", anchor=a)
    assert sorted(names(result)) == ["a", "b", "c"]
    assert len(result) == 3


def test_self_loop_does_not_infinite_loop():
    a = FakeFunc("a", 0x100)
    link(a, a)
    result = order_functions([a], "local-breadth", anchor=a)
    assert names(result) == ["a"]


def test_zero_caller_roots():
    root = FakeFunc("root", 0x100)
    leaf = FakeFunc("leaf", 0x200)
    link(root, leaf)
    assert zero_caller_roots([root, leaf]) == [root]


# --- Fuzz testing -----------------------------------------------------------


def _random_graph(rng, n, edge_prob=0.3, start=0x1000, step=0x10):
    funcs = [FakeFunc(f"f{i}", start + i * step) for i in range(n)]
    for i in range(n):
        for j in range(n):
            if i != j and rng.random() < edge_prob:
                link(funcs[i], funcs[j])
    return funcs


@pytest.mark.parametrize("seed", range(25))
def test_fuzz_all_orderings_return_permutation(seed):
    rng = random.Random(seed)
    n = rng.randint(1, 12)
    funcs = _random_graph(rng, n, edge_prob=rng.uniform(0.0, 0.6))
    anchor = rng.choice(funcs)
    roots = rng.sample(funcs, k=rng.randint(1, n))

    for strategy in (
        "default",
        "leaves-first",
        "info-gain",
        "local-breadth",
        "local-bottom-up",
        "local-up",
        "top-down",
        "export-down",
    ):
        kwargs = {}
        if strategy in ("local-breadth", "local-bottom-up", "local-up"):
            kwargs["anchor"] = anchor
        if strategy in ("top-down", "export-down"):
            kwargs["roots"] = roots

        result = order_functions(funcs, strategy, **kwargs)

        assert len(result) == len(funcs), strategy
        assert {f.start for f in result} == {f.start for f in funcs}, strategy
        assert len(result) == len(set(f.start for f in result)), strategy


@pytest.mark.parametrize("seed", range(10))
def test_fuzz_restrict_to_never_crashes(seed):
    rng = random.Random(seed)
    n = rng.randint(2, 10)
    funcs = _random_graph(rng, n, edge_prob=rng.uniform(0.0, 0.5))
    anchor = rng.choice(funcs)
    restrict_to = rng.sample(funcs, k=rng.randint(1, n))

    for strategy in ("local-breadth", "local-bottom-up", "local-up"):
        result = order_functions(funcs, strategy, anchor=anchor, restrict_to=restrict_to)
        assert {f.start for f in result} == {f.start for f in funcs}
