"""Anti-self-judge policy: default + exclusion semantics."""

from __future__ import annotations

from multicooker.judging_policy import (
    DEFAULT_POLICY,
    excluded_pairs,
    judging_policy,
)


PARTICIPANTS = [
    {"name": "alice", "flavor": "claude"},
    {"name": "bob", "flavor": "codex"},
]
JUDGES = [
    {"name": "judge-claude", "flavor": "claude"},
    {"name": "judge-gemini", "flavor": "gemini"},
]


def test_default_is_warn():
    assert DEFAULT_POLICY == "warn"
    assert judging_policy({}) == "warn"
    assert judging_policy({"judging": {}}) == "warn"
    assert judging_policy({"judging": {"policy": "bogus"}}) == "warn"


def test_explicit_policy_read():
    assert judging_policy({"judging": {"policy": "require_distinct_flavor"}}) \
        == "require_distinct_flavor"
    assert judging_policy({"judging": {"policy": "allow_self"}}) == "allow_self"


def test_excluded_only_under_strict():
    # warn / allow_self keep everything.
    assert excluded_pairs(PARTICIPANTS, JUDGES, "warn") == set()
    assert excluded_pairs(PARTICIPANTS, JUDGES, "allow_self") == set()
    # strict drops the same-flavor pair only.
    strict = excluded_pairs(PARTICIPANTS, JUDGES, "require_distinct_flavor")
    assert strict == {("judge-claude", "alice")}


def test_excluded_multiple_same_flavor():
    participants = [
        {"name": "a", "flavor": "claude"},
        {"name": "b", "flavor": "claude"},
        {"name": "c", "flavor": "codex"},
    ]
    judges = [{"name": "jc", "flavor": "claude"}]
    strict = excluded_pairs(participants, judges, "require_distinct_flavor")
    assert strict == {("jc", "a"), ("jc", "b")}
