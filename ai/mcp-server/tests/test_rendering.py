"""Unit tests for rendering.py's BN-independent helpers (filter/project/
paginate/render_table/render_kv). Unlike tests/run.py, this needs no
running Binary Ninja -- run directly: `python3 tests/test_rendering.py`.

`tool_result`/`_target_marker` (the only BN-touching parts of the module)
are deliberately not covered here; they need a real BinaryView and are
exercised via tests/run.py instead.
"""

import importlib.util
import sys
from pathlib import Path

_HERE = Path(__file__).resolve()
_PLUGIN_DIR = _HERE.parent.parent

spec = importlib.util.spec_from_file_location("rendering", _PLUGIN_DIR / "rendering.py")
rendering = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rendering)

_PASS, _FAIL = [], []


def _report(status, name, detail=""):
    bucket = {"PASS": _PASS, "FAIL": _FAIL}[status]
    bucket.append(name)
    line = f"[{status}] {name}"
    if detail:
        line += f" -- {detail}"
    print(line)


def check(name, fn):
    try:
        fn()
        _report("PASS", name)
    except Exception as e:
        _report("FAIL", name, str(e))


ROWS = [
    {"name": "main", "addr": "0x401000"},
    {"name": "sub_401020", "addr": "0x401020"},
    {"name": "helper", "addr": "0x401050"},
]


def test_filter_rows_no_pattern():
    assert rendering.filter_rows(ROWS, None, "name") == ROWS
    assert rendering.filter_rows(ROWS, "", "name") == ROWS


def test_filter_rows_substring_case_insensitive():
    result = rendering.filter_rows(ROWS, "MAIN", "name")
    assert [r["name"] for r in result] == ["main"]


def test_filter_rows_regex():
    result = rendering.filter_rows(ROWS, "^sub_", "name")
    assert [r["name"] for r in result] == ["sub_401020"]


def test_filter_rows_missing_key():
    rows = [{"name": "a"}, {"other": "b"}]
    result = rendering.filter_rows(rows, "a", "name")
    assert result == [{"name": "a"}]


def test_project_no_fields():
    assert rendering.project(ROWS, None) == ROWS
    assert rendering.project(ROWS, []) == ROWS


def test_project_narrows_and_orders():
    result = rendering.project(ROWS, ["addr"])
    assert result == [{"addr": r["addr"]} for r in ROWS]


def test_project_missing_field_is_none():
    result = rendering.project([{"name": "a"}], ["name", "missing"])
    assert result == [{"name": "a", "missing": None}]


def test_paginate():
    assert rendering.paginate(ROWS, limit=2, offset=0) == ROWS[:2]
    assert rendering.paginate(ROWS, limit=2, offset=1) == ROWS[1:3]
    assert rendering.paginate(ROWS, limit=100, offset=100) == []


def test_render_table_header_and_rows():
    text = rendering.render_table(ROWS)
    lines = text.split("\n")
    assert lines[0] == "name\taddr"
    assert lines[1] == "main\t0x401000"
    assert len(lines) == 1 + len(ROWS)


def test_render_table_respects_fields_order():
    text = rendering.render_table(ROWS, fields=["addr", "name"])
    assert text.split("\n")[0] == "addr\tname"
    assert text.split("\n")[1] == "0x401000\tmain"


def test_render_table_empty():
    assert rendering.render_table([]) == "(no results)"


def test_render_table_none_value_is_blank_cell():
    text = rendering.render_table([{"a": "x", "b": None}])
    assert text.split("\n")[1] == "x\t"


def test_render_kv():
    text = rendering.render_kv({"name": "main", "start": "0x401000"})
    assert text == "name: main\nstart: 0x401000"


def main():
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            check(name, fn)
    print(f"\n{len(_PASS)} passed, {len(_FAIL)} failed")
    return 1 if _FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
