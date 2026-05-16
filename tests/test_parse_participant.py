"""Tests for new_cook.parse_participant — the NAME[=FLAVOR] grammar.

Covered: bare names, NAME=FLAVOR, whitespace, error shapes.
Not covered here: duplicate-name detection (lives in new_cook itself).
"""

from __future__ import annotations

import pytest

from multicooker.new_cook import parse_participant


def test_bare_name_uses_same_flavor():
    assert parse_participant("claude") == ("claude", "claude")


def test_explicit_flavor():
    assert parse_participant("claude-a=claude") == ("claude-a", "claude")


def test_strips_whitespace():
    assert parse_participant("  claude  ") == ("claude", "claude")
    assert parse_participant(" claude-a = claude ") == ("claude-a", "claude")


def test_empty_segments_rejected():
    with pytest.raises(ValueError, match="bad participant spec"):
        parse_participant("=claude")
    with pytest.raises(ValueError, match="bad participant spec"):
        parse_participant("claude=")
    with pytest.raises(ValueError, match="bad participant spec"):
        parse_participant("=")


def test_only_first_equals_splits():
    # Flavor names don't contain '=', but if someone is creative we should
    # not silently corrupt the flavor.
    name, flavor = parse_participant("a=b=c")
    assert name == "a"
    assert flavor == "b=c"
