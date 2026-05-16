"""Tests for runner_common.detect_rate_limit.

Sample stdout snippets per CLI cover both real rate-limit messages we've
observed in arena runs and benign output that must NOT trigger a
rate-limit classification (false-positive guard).

If Anthropic / OpenAI / Google change their rate-limit phrasing, these
tests catch the regression here instead of in production cook output.
"""

from __future__ import annotations

import pytest

from multicooker.runner_common import detect_rate_limit


# ---- claude ---------------------------------------------------------------

def test_claude_5_hour_limit():
    text = "Error: 5-hour limit reached. Resets at 9:30am."
    rl, retry, ev = detect_rate_limit("claude", text)
    assert rl is True
    assert "5-hour limit reached" in ev
    assert retry > 0


def test_claude_weekly_limit():
    text = "Sorry, you've hit your weekly limit reached for Claude."
    rl, retry, ev = detect_rate_limit("claude", text)
    assert rl is True


def test_claude_usage_limit():
    text = "Usage limit reached. Please try again later."
    rl, _, _ = detect_rate_limit("claude", text)
    assert rl is True


def test_claude_no_false_positive_on_normal_output():
    # "limit" appears in normal prose but not in a rate-limit phrase.
    text = "Here is the limit theorem: lim x→0 f(x) = 1. Done."
    rl, _, _ = detect_rate_limit("claude", text)
    assert rl is False


# ---- codex ----------------------------------------------------------------

def test_codex_usage_limit():
    text = "You hit your usage limit. Try again at 14:00."
    rl, retry, _ = detect_rate_limit("codex", text)
    assert rl is True
    assert retry > 0


def test_codex_resets_in_hours():
    text = "Quota exceeded. Resets in 3 hours."
    rl, retry, _ = detect_rate_limit("codex", text)
    assert rl is True
    assert retry == 3 * 3600


def test_codex_resets_in_minutes():
    text = "Plan limit. Resets in 15 minutes."
    rl, retry, _ = detect_rate_limit("codex", text)
    assert rl is True
    assert retry == 15 * 60


def test_codex_too_many_requests():
    text = "HTTP 429 Too Many Requests"
    rl, _, _ = detect_rate_limit("codex", text)
    assert rl is True


# ---- gemini ---------------------------------------------------------------

def test_gemini_quota_exceeded():
    text = "Resource quota exceeded for project xyz."
    rl, _, _ = detect_rate_limit("gemini", text)
    assert rl is True


def test_gemini_retry_after():
    text = "Rate limited. retry-after: 120"
    rl, retry, _ = detect_rate_limit("gemini", text)
    assert rl is True
    assert retry == 120


def test_gemini_daily_limit():
    text = "You have reached your daily limit for the free tier."
    rl, _, _ = detect_rate_limit("gemini", text)
    assert rl is True


# ---- common ---------------------------------------------------------------

def test_unknown_flavor_returns_false():
    rl, retry, ev = detect_rate_limit("dummy", "rate limit reached")
    # No patterns registered for dummy → never flagged.
    assert rl is False
    assert retry == 0
    assert ev == ""


def test_empty_text():
    rl, retry, ev = detect_rate_limit("claude", "")
    assert rl is False
    assert retry == 0
    assert ev == ""


@pytest.mark.parametrize("flavor", ["claude", "codex", "gemini"])
def test_evidence_includes_context(flavor):
    text = "lots of preamble " * 10 + "rate limit hit here" + " trailing context " * 10
    rl, _, ev = detect_rate_limit(flavor, text)
    if rl:
        # Evidence should be non-empty and short-ish.
        assert ev
        assert len(ev) < 400
