from __future__ import annotations

from kaggle_mcp import formatting


class _Obj:
    def __init__(self, **kw):
        self.__dict__.update(kw)


def test_obj_to_dict_defensive():
    o = _Obj(ref="a/b", title="T")
    d = formatting.obj_to_dict(o, ["ref", "title", "missing"])
    assert d == {"ref": "a/b", "title": "T", "missing": None}


def test_cap_list():
    assert formatting.cap_list(range(100), 3) == [0, 1, 2]


def test_truncate_text_marks_truncation():
    out = formatting.truncate_text("x" * 30, limit=10)
    assert out.startswith("x" * 10)
    assert "truncated" in out


def test_markdown_table_escapes_pipes_and_newlines():
    rows = [{"a": "x|y", "b": "line1\nline2"}]
    md = formatting.markdown_table(rows, ["a", "b"])
    assert "x\\|y" in md
    assert "line1 line2" in md
    assert md.startswith("| a | b |")


def test_markdown_table_empty():
    assert formatting.markdown_table([], ["a"]) == "_(no results)_"


def test_paginated_envelope():
    env = formatting.paginated([1, 2], page=1, page_size=2)
    assert env["has_more"] is True
    assert env["next_page"] == 2
    env2 = formatting.paginated([1], page=1, page_size=2)
    assert env2["has_more"] is False
    assert env2["next_page"] is None
