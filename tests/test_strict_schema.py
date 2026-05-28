"""Strict judge schema validation (item 14) — pure function + brief schema."""

from __future__ import annotations

from multicooker.brief_schema import validate
from multicooker.judge import _strict_canonical


def _good_brief() -> dict:
    return {
        "name": "smoke",
        "participants": [{"name": "a", "flavor": "claude"}],
        "judges": [{"name": "j", "flavor": "codex"}],
    }


def test_strict_accepts_canonical():
    s = {"A": {"dimensions": {"correctness": 4, "quality": 3}, "total": 35},
         "B": {"dimensions": {"correctness": 2, "quality": 5}}}
    assert _strict_canonical(s) == s


def test_strict_rejects_flat_form():
    # Flat per-label dims with no "dimensions" wrapper — tolerant mode lifts
    # these, strict mode must reject.
    assert _strict_canonical({"A": {"correctness": 4, "quality": 3}}) is None


def test_strict_rejects_scores_wrapper():
    assert _strict_canonical({"scores": {"A": {"dimensions": {"x": 1}}}}) is None


def test_strict_rejects_float_dimension():
    assert _strict_canonical({"A": {"dimensions": {"x": 4.5}}}) is None


def test_strict_rejects_bool_dimension():
    assert _strict_canonical({"A": {"dimensions": {"x": True}}}) is None


def test_strict_rejects_non_int_total():
    assert _strict_canonical({"A": {"dimensions": {"x": 4}, "total": 4.5}}) is None


def test_strict_rejects_empty_dimensions():
    assert _strict_canonical({"A": {"dimensions": {}}}) is None


def test_strict_rejects_empty_and_non_dict():
    assert _strict_canonical({}) is None
    assert _strict_canonical("nope") is None
    assert _strict_canonical({"A": "nope"}) is None


def test_brief_strict_schema_bool_ok():
    cfg = _good_brief()
    cfg["judging"] = {"strict_schema": True}
    assert validate(cfg) == []
    cfg["judging"] = {"strict_schema": False}
    assert validate(cfg) == []


def test_brief_strict_schema_rejects_non_bool():
    cfg = _good_brief()
    cfg["judging"] = {"strict_schema": "yes"}
    errs = validate(cfg)
    assert any("strict_schema" in e for e in errs)
