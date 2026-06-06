"""Shared types + helpers for runners.

The only runner now is `compose_runner` (docker-mode). This module keeps the
data shape and the rate-limit detector that the runner uses to classify a
participant's exit. Was previously split between `host_runner.py` and
`compose_runner.py`; host-mode is dead so the helpers moved here.
"""

from __future__ import annotations

import re
import shutil
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
    start_failed: bool = False
    oom_killed: bool = False


def classify_cell(res: "RunResult") -> str:
    """Map a RunResult to a contract cell state (see state.py constants).

    Order matters: start/oom/rate-limit/timeout are more specific than a bare
    non-zero exit and must win. Kept here (next to RunResult) so cook and
    refine classify identically.
    """
    if res.start_failed:
        return "start_failed"
    if res.oom_killed:
        return "oom_killed"
    if res.rate_limited:
        return "rate_limited"
    if res.timed_out:
        return "timed_out"
    if res.exit_code == 0:
        return "ok"
    return "non_zero_exit"


def validate_outputs(out_dir: Path, required: list[dict] | None) -> list[str]:
    """Return the declared required output paths absent from out_dir.

    A required path is satisfied only by a real (non-symlink) regular file with
    nonzero size — an empty RESULT.md or a symlink isn't a deliverable. `kind`
    is not enforced here; presence is the contract (see docs item 12).
    """
    missing: list[str] = []
    for spec in required or []:
        rel = (spec or {}).get("path") if isinstance(spec, dict) else None
        if not rel:
            continue
        p = out_dir / rel
        ok = p.is_file() and not p.is_symlink() and p.stat().st_size > 0
        if not ok:
            missing.append(rel)
    return missing


def apply_required_outputs(status: str, out_dir: Path,
                           required: list[dict] | None) -> tuple[str, list[str]]:
    """Downgrade an otherwise-ok cell to artifact_missing if declared outputs
    are absent. Returns (status, missing_paths).

    Only fires when the process actually exited cleanly (status == "ok"): a
    rate-limit/timeout/non-zero/oom/start_failed is a more specific truth and
    must not be masked by artifact validation. Shared by cook and refine so
    they classify identically.
    """
    if status != "ok" or not required:
        return status, []
    missing = validate_outputs(out_dir, required)
    if missing:
        return "artifact_missing", missing
    return status, []


_RATE_LIMIT_ERROR_PATTERNS = [
    re.compile(
        r"\brate[-_ ]?limit(?:ed)?\s+(?:reached|exceeded|exhausted|hit)\b",
        re.I,
    ),
    re.compile(r"\brate[_-]?limit[_-]?(?:reached|exceeded|exhausted|hit)\b", re.I),
]


_QUOTA_EXHAUSTED_PATTERNS = [
    re.compile(
        r"^\s*(?:error[: ]+)?(?:resource\s+)?quota\s+(?:exceeded|exhausted)\b",
        re.I | re.M,
    ),
]


_RL_PATTERNS = {
    "claude": [
        re.compile(r"5[- ]hour limit reached", re.I),
        re.compile(r"weekly limit reached", re.I),
        re.compile(r"usage limit reached", re.I),
        re.compile(r"hit your limit", re.I),
        *_RATE_LIMIT_ERROR_PATTERNS,
        re.compile(r"resets?\s+(?:at\s+)?(\d{1,2}):(\d{2})\s*(am|pm)?", re.I),
        re.compile(r"please try again later", re.I),
    ],
    "codex": [
        re.compile(r"hit your usage limit", re.I),
        re.compile(r"try again at (\d{1,2}):(\d{2})\s*(am|pm)?", re.I),
        re.compile(r"usage limit", re.I),
        *_RATE_LIMIT_ERROR_PATTERNS,
        *_QUOTA_EXHAUSTED_PATTERNS,
        re.compile(r"plan limit", re.I),
        re.compile(r"too many requests", re.I),
        re.compile(r"resets? in (\d+)\s*(hour|hours|h|minute|minutes|m)", re.I),
    ],
    "agy": [
        # agy (Google Antigravity CLI) surfaces Google-style quota errors,
        # same shapes gemini-cli used.
        *_QUOTA_EXHAUSTED_PATTERNS,
        re.compile(r"resource.*exhausted", re.I),
        *_RATE_LIMIT_ERROR_PATTERNS,
        re.compile(r"daily.*limit", re.I),
        re.compile(r"retry.after[: ]+(\d+)", re.I),
    ],
    "grok": [
        # Patterns inferred from xAI billing / cli-chat-proxy error surfaces.
        # Real signatures will land once we have a rate-limited cook to study;
        # until then these cover the obvious shapes (subscription gate, 429s).
        re.compile(r"subscription.*required", re.I),
        *_RATE_LIMIT_ERROR_PATTERNS,
        re.compile(r"too many requests", re.I),
        *_QUOTA_EXHAUSTED_PATTERNS,
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


# Build artifacts + dep caches that should never be snapshotted/sealed.
# Snapshotting them blows up disk (10s of GB per round) and CPU (millions
# of inodes for pnpm-style content stores). Matched by basename.
#
# NOTE: `out` is deliberately NOT here even though it's a common build dir
# in some ecosystems — multicooker's whole convention is that participants
# write their submission to `./out/`. An ignore on "out" silently strips
# every submission during the anonymize step.
_DEFAULT_IGNORE = frozenset({
    "node_modules", ".pnpm-store", ".yarn", ".npm",
    ".expo", ".turbo", ".next", ".nuxt", ".svelte-kit",
    "dist", "build", ".output",
    "Pods", "DerivedData", ".gradle",
    "__pycache__", ".venv", "venv", ".pytest_cache", ".mypy_cache",
    "target",
    ".DS_Store",
})


def _read_gitignore_basenames(src: Path) -> set[str]:
    """Read top-level basename entries from src/.gitignore.

    Only basename-style entries are honored (no slashes, no globs, no
    negation) — covers the 99% case where participants want to exclude
    things like `node_modules` or `secret.env` without writing a full
    gitignore parser.
    """
    gi = src / ".gitignore"
    if not gi.exists():
        return set()
    out: set[str] = set()
    for line in gi.read_text().splitlines():
        line = line.strip().rstrip("/")
        if not line or line.startswith("#") or line.startswith("!"):
            continue
        if "/" in line or "*" in line or "?" in line or "[" in line:
            continue
        out.add(line)
    return out


def copytree_clean(src: Path, dst: Path) -> None:
    """shutil.copytree that skips build artifacts and .gitignore basenames.

    Used by cook/refine/judge to snapshot or seal participant output
    without dragging in node_modules, pnpm stores, build dirs, etc.
    """
    extras = _read_gitignore_basenames(src)
    patterns = _DEFAULT_IGNORE | extras

    def _ignore(_dirpath: str, names: list[str]) -> set[str]:
        return {n for n in names if n in patterns}

    shutil.copytree(src, dst, ignore=_ignore)
