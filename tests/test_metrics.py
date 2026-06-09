from __future__ import annotations

import json
from pathlib import Path

from multicooker import metrics


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n")


def test_collect_claude_usage(tmp_path: Path):
    cook = tmp_path / "cook"
    path = cook / "work" / "claude" / "usage" / "claude" / "projects" / "p" / "s.jsonl"
    _write_jsonl(path, [
        {
            "message": {
                "model": "claude-sonnet",
                "usage": {
                    "input_tokens": 100,
                    "output_tokens": 20,
                    "cache_creation_input_tokens": 5,
                    "cache_read_input_tokens": 7,
                },
            },
            "costUSD": 0.01,
        }
    ])

    usage = metrics.collect_usage(cook, "participant", "claude", "claude")

    assert usage is not None
    assert usage["total_tokens"] == 132
    assert usage["input_tokens"] == 100
    assert usage["output_tokens"] == 20
    assert usage["models"] == ["claude-sonnet"]
    assert usage["cost_usd"] == 0.01


def test_collect_codex_usage_from_last_token_usage(tmp_path: Path):
    cook = tmp_path / "cook"
    path = cook / "work" / "codex" / "usage" / "codex" / "sessions" / "s.jsonl"
    _write_jsonl(path, [
        {"type": "turn_context", "payload": {"model": "gpt-5"}},
        {
            "type": "event_msg",
            "timestamp": "2026-01-01T00:00:00Z",
            "payload": {
                "type": "token_count",
                "info": {
                    "last_token_usage": {
                        "input_tokens": 10,
                        "cached_input_tokens": 3,
                        "output_tokens": 4,
                        "reasoning_output_tokens": 2,
                    }
                },
            },
        },
    ])

    usage = metrics.collect_usage(cook, "participant", "codex", "codex")

    assert usage is not None
    assert usage["total_tokens"] == 19
    assert usage["cached_input_tokens"] == 3
    assert usage["reasoning_output_tokens"] == 2
    assert usage["models"] == ["gpt-5"]


def test_collect_codex_usage_from_metadata_model(tmp_path: Path):
    cook = tmp_path / "cook"
    path = cook / "work" / "codex" / "usage" / "codex" / "sessions" / "s.jsonl"
    _write_jsonl(path, [
        {"type": "session_configured", "payload": {"metadata": {"model": "gpt-5.1"}}},
        {
            "type": "event_msg",
            "timestamp": "2026-01-01T00:00:00Z",
            "payload": {
                "type": "token_count",
                "info": {
                    "last_token_usage": {
                        "input_tokens": 10,
                        "output_tokens": 4,
                    }
                },
            },
        },
    ])

    usage = metrics.collect_usage(cook, "participant", "codex", "codex")

    assert usage is not None
    assert usage["models"] == ["gpt-5.1"]


def test_collect_codex_usage_from_total_delta(tmp_path: Path):
    cook = tmp_path / "cook"
    path = cook / "work" / "codex" / "usage" / "codex" / "sessions" / "s.jsonl"
    _write_jsonl(path, [
        {
            "type": "event_msg",
            "timestamp": "2026-01-01T00:00:00Z",
            "payload": {
                "type": "token_count",
                "info": {
                    "total_token_usage": {
                        "input_tokens": 10,
                        "output_tokens": 4,
                        "cache_creation_input_tokens": 2,
                        "tool_tokens": 3,
                    }
                },
            },
        },
        {
            "type": "event_msg",
            "timestamp": "2026-01-01T00:00:01Z",
            "payload": {
                "type": "token_count",
                "info": {
                    "total_token_usage": {
                        "input_tokens": 15,
                        "output_tokens": 6,
                        "cache_creation_input_tokens": 5,
                        "tool_tokens": 4,
                    }
                },
            },
        },
    ])

    usage = metrics.collect_usage(cook, "participant", "codex", "codex")

    assert usage is not None
    assert usage["input_tokens"] == 15
    assert usage["output_tokens"] == 6
    assert usage["cache_creation_input_tokens"] == 5
    assert usage["tool_tokens"] == 4
    assert usage["total_tokens"] == 30


def test_collect_agy_usage(tmp_path: Path):
    cook = tmp_path / "cook"
    path = cook / "work" / "agy" / "usage" / "agy" / "tmp" / "chat.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "stats": {
            "models": {
                "agy-2.5-pro": {
                    "tokens": {
                        "input": 11,
                        "output": 13,
                        "cached": 2,
                        "thoughts": 3,
                    }
                }
            }
        }
    }))

    usage = metrics.collect_usage(cook, "participant", "agy", "agy")

    assert usage is not None
    assert usage["total_tokens"] == 29
    assert usage["cache_read_input_tokens"] == 2
    assert usage["reasoning_output_tokens"] == 3
    assert usage["models"] == ["agy-2.5-pro"]


def test_sum_usage_aggregates_and_dedups_models():
    a = {"input_tokens": 100, "output_tokens": 20, "total_tokens": 120,
         "cost_usd": 0.01, "models": ["claude-sonnet"]}
    b = {"input_tokens": 10, "output_tokens": 4, "total_tokens": 14,
         "cost_usd": 0.02, "models": ["gpt-5", "claude-sonnet"]}

    totals = metrics.sum_usage([a, None, b])

    assert totals is not None
    assert totals["input_tokens"] == 110
    assert totals["output_tokens"] == 24
    assert totals["total_tokens"] == 134
    assert totals["cost_usd"] == 0.03
    assert totals["models"] == ["claude-sonnet", "gpt-5"]


def test_sum_usage_returns_none_when_empty():
    assert metrics.sum_usage([]) is None
    assert metrics.sum_usage([None, {}]) is None


def test_summarize_usage_formats_known_fields():
    text = metrics.summarize_usage({
        "total_tokens": 1234,
        "input_tokens": 1000,
        "output_tokens": 200,
        "cache_read_input_tokens": 34,
        "cost_usd": 0.0123,
    })
    assert "1,234 tok" in text
    assert "in 1,000" in text
    assert "out 200" in text
    assert "cache 34" in text
    assert "$0.0123" in text


def test_summarize_usage_handles_missing():
    assert metrics.summarize_usage(None) == "n/a"
    assert metrics.summarize_usage({}) == "0 tok"


def test_collect_cell_usage_maps_role(tmp_path: Path):
    cook = tmp_path / "cook"
    path = cook / "work" / "claude" / "usage" / "claude" / "projects" / "p" / "s.jsonl"
    _write_jsonl(path, [
        {"message": {"model": "claude-sonnet",
                     "usage": {"input_tokens": 5, "output_tokens": 2}}},
    ])

    usage = metrics.collect_cell_usage(cook, "participant", "claude", "claude")
    assert usage is not None
    assert usage["total_tokens"] == 7

    assert metrics.collect_cell_usage(cook, "judge", "claude", None) is None
    assert metrics.collect_cell_usage(cook, "bogus", "claude", "claude") is None


def test_collect_cell_usage_judge_tree(tmp_path: Path):
    """Judge usage lives under a different tree (judging/_usage/...)."""
    cook = tmp_path / "cook"
    path = (cook / "judging" / "_usage" / "judge-claude" / "claude"
            / "projects" / "p" / "s.jsonl")
    _write_jsonl(path, [
        {"message": {"model": "claude-sonnet",
                     "usage": {"input_tokens": 8, "output_tokens": 3}}},
    ])

    usage = metrics.collect_cell_usage(cook, "judge", "judge-claude", "claude")
    assert usage is not None
    assert usage["total_tokens"] == 11


def test_sum_usage_tolerates_non_list_models():
    # Hand-edited / future-schema usage with a non-list "models" must not crash.
    a = {"total_tokens": 10, "models": "claude-sonnet"}
    b = {"total_tokens": 5, "models": ["gpt-5"]}
    totals = metrics.sum_usage([a, b])
    assert totals is not None
    assert totals["total_tokens"] == 15
    assert totals["models"] == ["gpt-5"]
