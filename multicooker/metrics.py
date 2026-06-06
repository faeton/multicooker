"""Usage/timing helpers for cook cells.

Durations are measured by compose_runner. Token usage is best-effort: each
participant/judge gets a writable, cook-local mount at the CLI's normal usage
history path, then we parse the files left there. The parsers intentionally
mirror the simple shapes used by ccusage without depending on its Node stack.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class UsageTotals:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0
    cached_input_tokens: int = 0
    reasoning_output_tokens: int = 0
    tool_tokens: int = 0
    total_tokens: int = 0
    cost_usd: float = 0.0
    events: int = 0
    models: set[str] = field(default_factory=set)

    def add(self, usage: dict[str, Any], model: str | None = None,
            cost_usd: float | None = None) -> None:
        input_tokens = _num(usage, "input_tokens", "inputTokens", "input", "prompt",
                            "prompt_tokens")
        output_tokens = _num(usage, "output_tokens", "outputTokens", "output",
                             "candidates", "candidates_tokens")
        cache_creation = _num(usage, "cache_creation_input_tokens",
                              "cacheCreationInputTokens", "cacheCreationTokens")
        cache_read = _num(usage, "cache_read_input_tokens", "cacheReadInputTokens",
                          "cacheReadTokens")
        cached = _num(usage, "cached_input_tokens", "cachedInputTokens", "cached",
                      "cached_tokens")
        reasoning = _num(usage, "reasoning_output_tokens", "reasoningOutputTokens",
                         "reasoning", "reasoning_tokens", "thoughts",
                         "thoughts_tokens")
        tool = _num(usage, "tool_tokens", "toolTokens", "tool")
        total = _num(usage, "total_tokens", "totalTokens", "total")
        if total <= 0:
            total = (
                input_tokens + output_tokens + cache_creation + cache_read
                + cached + reasoning + tool
            )

        if (
            input_tokens == 0 and output_tokens == 0 and cache_creation == 0
            and cache_read == 0 and cached == 0 and reasoning == 0 and tool == 0
            and total == 0
        ):
            return

        self.input_tokens += input_tokens
        self.output_tokens += output_tokens
        self.cache_creation_input_tokens += cache_creation
        self.cache_read_input_tokens += cache_read
        self.cached_input_tokens += cached
        self.reasoning_output_tokens += reasoning
        self.tool_tokens += tool
        self.total_tokens += total
        if cost_usd is not None:
            self.cost_usd += cost_usd
        self.events += 1
        if model:
            self.models.add(model)

    def to_dict(self, flavor: str, source_path: Path) -> dict[str, Any] | None:
        if self.events == 0:
            return None
        out: dict[str, Any] = {
            "source": flavor,
            "source_path": str(source_path),
            "events": self.events,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cache_creation_input_tokens": self.cache_creation_input_tokens,
            "cache_read_input_tokens": self.cache_read_input_tokens,
            "cached_input_tokens": self.cached_input_tokens,
            "reasoning_output_tokens": self.reasoning_output_tokens,
            "tool_tokens": self.tool_tokens,
            "total_tokens": self.total_tokens,
        }
        if self.cost_usd:
            out["cost_usd"] = round(self.cost_usd, 6)
        if self.models:
            out["models"] = sorted(self.models)
        return out


def usage_root(cook_dir: Path, cell_kind: str, name: str, flavor: str) -> Path:
    if cell_kind == "participant":
        return cook_dir / "work" / name / "usage" / flavor
    if cell_kind == "judge":
        return cook_dir / "judging" / "_usage" / name / flavor
    raise ValueError(f"unknown cell kind: {cell_kind}")


def prepare_usage_dir(cook_dir: Path, cell_kind: str, name: str, flavor: str) -> Path:
    root = usage_root(cook_dir, cell_kind, name, flavor)
    for subdir in _flavor_subdirs(flavor):
        (root / subdir).mkdir(parents=True, exist_ok=True)
    return root


def reset_usage_dir(cook_dir: Path, cell_kind: str, name: str, flavor: str) -> Path:
    root = usage_root(cook_dir, cell_kind, name, flavor)
    if root.exists():
        shutil.rmtree(root)
    return prepare_usage_dir(cook_dir, cell_kind, name, flavor)


def collect_usage(cook_dir: Path, cell_kind: str, name: str,
                  flavor: str) -> dict[str, Any] | None:
    root = usage_root(cook_dir, cell_kind, name, flavor)
    if flavor == "claude":
        return _collect_claude(root).to_dict(flavor, root)
    if flavor == "codex":
        return _collect_codex(root).to_dict(flavor, root)
    if flavor == "agy":
        return _collect_agy(root).to_dict(flavor, root)
    return None


def _flavor_subdirs(flavor: str) -> list[str]:
    if flavor == "claude":
        return ["projects"]
    if flavor == "codex":
        return ["sessions"]
    if flavor == "agy":
        return ["tmp", "history"]
    return []


def _collect_claude(root: Path) -> UsageTotals:
    totals = UsageTotals()
    for line_obj in _iter_jsonl(root / "projects"):
        if not isinstance(line_obj, dict):
            continue
        message = _record(line_obj.get("message"))
        usage = (
            _record_or_none(line_obj.get("usage"))
            or _record_or_none(message.get("usage"))
        )
        if usage is None:
            continue
        model = _str(message.get("model")) or _str(line_obj.get("model"))
        totals.add(usage, model=model, cost_usd=_float(line_obj.get("costUSD")))
    return totals


def _collect_codex(root: Path) -> UsageTotals:
    totals = UsageTotals()
    for file in sorted((root / "sessions").rglob("*.jsonl")):
        previous_total: dict[str, Any] | None = None
        current_model: str | None = None
        for line_obj in _iter_jsonl_file(file):
            if not isinstance(line_obj, dict):
                continue
            payload = _record(line_obj.get("payload"))
            context_model = _extract_model(payload, line_obj)
            if context_model is not None:
                current_model = context_model
            if line_obj.get("type") == "turn_context":
                continue
            if line_obj.get("type") != "event_msg":
                continue
            if payload.get("type") != "token_count":
                continue
            info = _record(payload.get("info"))
            model = _extract_model(info, payload, line_obj) or current_model
            last_usage = _record_or_none(info.get("last_token_usage"))
            total_usage = _record_or_none(info.get("total_token_usage"))
            usage = last_usage
            if usage is None and total_usage is not None:
                usage = _subtract_usage(total_usage, previous_total)
            if total_usage is not None:
                previous_total = total_usage
            if usage is not None:
                totals.add(usage, model=model)
    return totals


# agy (Google Antigravity CLI) inherits gemini-cli's ~/.gemini layout. This
# parser is carried over verbatim; agy's own antigravity-cli/ telemetry schema
# may differ, in which case totals come back empty until the parser is extended.
def _collect_agy(root: Path) -> UsageTotals:
    totals = UsageTotals()
    for base in (root / "tmp", root / "history"):
        for file in sorted([*base.rglob("*.json"), *base.rglob("*.jsonl")]):
            if file.suffix == ".jsonl":
                for obj in _iter_jsonl_file(file):
                    _add_agy_object(totals, obj)
            else:
                try:
                    _add_agy_object(totals, json.loads(file.read_text()))
                except (OSError, json.JSONDecodeError):
                    continue
    return totals


def _add_agy_object(totals: UsageTotals, obj: Any) -> None:
    record = _record(obj)
    if not record:
        return
    messages = record.get("messages")
    if isinstance(messages, list):
        for message in messages:
            _add_agy_object(totals, message)
        return
    stats = (
        _record(record.get("stats"))
        or _record(_record(record.get("result")).get("stats"))
    )
    if stats:
        models = _record(stats.get("models"))
        if models:
            for model, payload in models.items():
                tokens = _record(_record(payload).get("tokens"))
                if tokens:
                    totals.add(_agy_tokens(tokens), model=model)
            return
        totals.add(_agy_tokens(stats), model=_str(record.get("model")) or "unknown")
        return
    tokens = _record(record.get("tokens"))
    if tokens:
        totals.add(_agy_tokens(tokens), model=_str(record.get("model")))


def _iter_jsonl(root: Path):
    if not root.exists():
        return
    for file in sorted(root.rglob("*.jsonl")):
        yield from _iter_jsonl_file(file)


def _iter_jsonl_file(file: Path):
    try:
        with open(file, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    continue
    except OSError:
        return


def _subtract_usage(current: dict[str, Any],
                    previous: dict[str, Any] | None) -> dict[str, int]:
    keys = [
        "input_tokens",
        "cached_input_tokens",
        "cache_creation_input_tokens",
        "cache_read_input_tokens",
        "output_tokens",
        "reasoning_output_tokens",
        "tool_tokens",
        "total_tokens",
    ]
    return {
        key: max(int(_num(current, key) - _num(previous or {}, key)), 0)
        for key in keys
    }


def _agy_tokens(tokens: dict[str, Any]) -> dict[str, Any]:
    return {
        "input_tokens": _num(tokens, "input", "prompt", "input_tokens", "prompt_tokens"),
        "output_tokens": _num(tokens, "output", "candidates", "output_tokens",
                              "candidates_tokens"),
        "cache_read_input_tokens": _num(tokens, "cached", "cached_tokens"),
        "reasoning_output_tokens": _num(tokens, "thoughts", "reasoning",
                                        "thoughts_tokens", "reasoning_tokens"),
        "tool_tokens": _num(tokens, "tool", "tool_tokens"),
        "total_tokens": _num(tokens, "total"),
    }


def _extract_model(*records: dict[str, Any]) -> str | None:
    for record in records:
        model = _str(record.get("model")) or _str(record.get("model_name"))
        if model is not None:
            return model
        metadata = _record(record.get("metadata"))
        model = _str(metadata.get("model")) or _str(metadata.get("model_name"))
        if model is not None:
            return model
    return None


def _record(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _record_or_none(value: Any) -> dict[str, Any] | None:
    return value if isinstance(value, dict) else None


def _str(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _float(value: Any) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return None


def _num(record: dict[str, Any], *keys: str) -> int:
    for key in keys:
        value = record.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return max(int(value), 0)
    return 0
