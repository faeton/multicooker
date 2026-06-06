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
