"""Shared types + helpers for runners.

The only runner now is `compose_runner` (docker-mode). This module keeps the
data shape and the rate-limit detector that the runner uses to classify a
participant's exit. Was previously split between `host_runner.py` and
`compose_runner.py`; host-mode is dead so the helpers moved here.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass
class RunResult:
    flavor: str
    exit_code: int
    duration_s: float
    timed_out: bool
    stdout_path: Path
    stderr_path: Path
    rate_limited: bool = False
    retry_after_s: int = 0
    rate_limit_evidence: str = ""
    attempts: int = 1


_RL_PATTERNS = {
    "claude": [
        re.compile(r"5[- ]hour limit reached", re.I),
        re.compile(r"weekly limit reached", re.I),
        re.compile(r"usage limit reached", re.I),
        re.compile(r"hit your limit", re.I),
        re.compile(r"rate.?limit", re.I),
        re.compile(r"resets?\s+(?:at\s+)?(\d{1,2}):(\d{2})\s*(am|pm)?", re.I),
        re.compile(r"please try again later", re.I),
    ],
    "codex": [
        re.compile(r"hit your usage limit", re.I),
        re.compile(r"try again at (\d{1,2}):(\d{2})\s*(am|pm)?", re.I),
        re.compile(r"usage limit", re.I),
        re.compile(r"rate.?limit", re.I),
        re.compile(r"quota.*(exceeded|exhausted)", re.I),
        re.compile(r"plan limit", re.I),
        re.compile(r"too many requests", re.I),
        re.compile(r"resets? in (\d+)\s*(hour|hours|h|minute|minutes|m)", re.I),
    ],
    "gemini": [
        re.compile(r"quota.*(exceeded|exhausted)", re.I),
        re.compile(r"resource.*exhausted", re.I),
        re.compile(r"rate.?limit", re.I),
        re.compile(r"daily.*limit", re.I),
        re.compile(r"retry.after[: ]+(\d+)", re.I),
    ],
}


def detect_rate_limit(flavor: str, text: str) -> tuple[bool, int, str]:
    """Scan a CLI's combined output for rate-limit markers.

    Returns (rate_limited, retry_after_seconds, short_evidence_snippet).
    Unknown flavors get no patterns and always return (False, 0, "") — that's
    fine; we just won't treat their failures as rate-limits.
    """
    rate_limited = False
    evidence = ""
    retry_after = 0
    for pat in _RL_PATTERNS.get(flavor, []):
        m = pat.search(text)
        if not m:
            continue
        if not rate_limited:
            rate_limited = True
            evidence = text[max(0, m.start() - 80): m.end() + 80].replace("\n", " ").strip()
        if retry_after > 0:
            continue
        groups = m.groups()
        if not groups:
            continue
        # Three shapes of retry-after extraction, distinguished by what
        # group(2) holds (or its absence):
        #   hh:mm          → group(2) is digits (minute component)
        #   N hours/mins   → group(2) is a word ("hour"/"minute"/...)
        #   retry-after: N → only one group, the seconds value
        try:
            g2 = groups[1] if len(groups) >= 2 else None
            if g2 and g2.isdigit():
                hh, mm = int(groups[0]), int(g2)
                ampm = (groups[2] if len(groups) >= 3 and groups[2] else "").lower()
                if ampm == "pm" and hh < 12:
                    hh += 12
                if ampm == "am" and hh == 12:
                    hh = 0
                now = datetime.now()
                target = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
                if target <= now:
                    target = target.replace(day=target.day + 1)
                retry_after = int((target - now).total_seconds())
            elif g2:
                n = int(groups[0])
                unit = g2.lower()
                retry_after = n * (3600 if unit.startswith("h") else 60)
            else:
                retry_after = int(groups[0])
        except (ValueError, IndexError):
            retry_after = 0
    return rate_limited, retry_after, evidence


def tail(path: Path, n_bytes: int = 16384) -> str:
    try:
        with open(path, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - n_bytes))
            return f.read().decode("utf-8", errors="replace")
    except FileNotFoundError:
        return ""
