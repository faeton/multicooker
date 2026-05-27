"""Pick container resource limits based on the active docker host's size.

Why this module exists: the same `brief.yaml` should run on a 100 GiB
dev laptop (no artificial caps wanted) and on an 11 GiB shared VPS
sitting next to production services (caps mandatory to keep an
agent's npm spike from getting matomo OOM-killed). The host is
whatever `docker info` reports against the *current* docker context,
not whatever `/proc/meminfo` says about the local box — so remote
hosts via `DOCKER_HOST=ssh://…` or `docker context use …` work
without code knowing the difference.

Profiles:
  large   — host has plenty (≥32 GiB RAM). Emit no mem_limit/cpus
            (don't artificially throttle dev experiments). Cheap
            safeties (pids_limit, oom_score_adj, log caps) stay on.
  medium  — typical small VPS (8–32 GiB). 2g/1cpu per cell.
  small   — tight host (<8 GiB). 1g/0.5cpu per cell.
  auto    — detect (the default).

Override precedence (weakest to strongest):
  1. auto-detect from `docker info`
  2. MULTICOOKER_PROFILE=large|medium|small env var
  3. --profile CLI flag (cook/refine/judge)
  4. brief.yaml top-level resources.profile
  5. brief.yaml per-participant resources.{mem_limit,cpus}

Cheap safeties (always emitted regardless of profile):
  pids_limit=512, oom_score_adj=500, logging json-file
  max-size=10m max-file=3, ulimit nofile 4096/8192.
"""

from __future__ import annotations

import json
import os
import subprocess
from typing import Any


PROFILES: dict[str, dict[str, Any]] = {
    "large":  {"mem_limit": None, "cpus": None},
    "medium": {"mem_limit": "2g", "cpus": "1.0"},
    "small":  {"mem_limit": "1g", "cpus": "0.5"},
}

VALID_PROFILES = frozenset({"auto", *PROFILES.keys()})

# Cheap safeties — always on, independent of profile.
DEFAULT_PIDS_LIMIT = 512
DEFAULT_OOM_SCORE_ADJ = 500
DEFAULT_LOG_OPTS = {"max-size": "10m", "max-file": "3"}
DEFAULT_NOFILE = (4096, 8192)


def _gib(n_bytes: int) -> float:
    return n_bytes / (1024 ** 3)


def docker_info() -> dict[str, Any] | None:
    """Return `docker info` JSON for the active context, or None on failure.

    Returning None (rather than raising) lets callers degrade gracefully —
    if the daemon is unreachable we'd rather render compose without
    mem_limit than abort. The user already runs `multicooker doctor`
    for the hard preflight; this is best-effort.
    """
    try:
        out = subprocess.run(
            ["docker", "info", "--format", "{{json .}}"],
            capture_output=True, text=True, timeout=5,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    if out.returncode != 0:
        return None
    try:
        return json.loads(out.stdout)
    except (json.JSONDecodeError, ValueError):
        return None


def tier_from_mem(mem_gib: float) -> str:
    if mem_gib >= 32:
        return "large"
    if mem_gib >= 8:
        return "medium"
    return "small"


def resolve_profile(
    cli_override: str | None = None,
    cfg_override: str | None = None,
) -> dict[str, Any]:
    """Resolve to a concrete profile dict.

    Returns {"tier": str, "mem_limit": str|None, "cpus": str|None,
             "source": str, "host_mem_gib": float|None, "host_ncpu": int|None}.

    `source` explains where the tier came from (for `doctor --capacity`
    and friendlier error messages): "auto", "env:MULTICOOKER_PROFILE",
    "cli:--profile", "brief:resources.profile".
    """
    # Strongest wins. cli_override comes from --profile, cfg_override
    # from brief.yaml top-level.
    env = os.environ.get("MULTICOOKER_PROFILE")
    explicit: tuple[str, str] | None = None
    if cfg_override and cfg_override != "auto":
        explicit = (cfg_override, "brief:resources.profile")
    elif cli_override and cli_override != "auto":
        explicit = (cli_override, "cli:--profile")
    elif env and env != "auto":
        explicit = (env, "env:MULTICOOKER_PROFILE")

    info = docker_info()
    host_mem_gib = _gib(info["MemTotal"]) if info and "MemTotal" in info else None
    host_ncpu = info.get("NCPU") if info else None

    if explicit:
        tier, source = explicit
        if tier not in PROFILES:
            # Fall back to auto rather than failing the cook; CLI/schema
            # validation should have caught this earlier.
            tier = tier_from_mem(host_mem_gib) if host_mem_gib else "medium"
            source = "auto:fallback"
    elif host_mem_gib is not None:
        tier = tier_from_mem(host_mem_gib)
        source = "auto"
    else:
        # No docker info available — be conservative.
        tier = "medium"
        source = "auto:no-docker"

    p = PROFILES[tier]
    return {
        "tier": tier,
        "mem_limit": p["mem_limit"],
        "cpus": p["cpus"],
        "source": source,
        "host_mem_gib": host_mem_gib,
        "host_ncpu": host_ncpu,
    }


# Bytes parser for "512m" / "2g" / 2_147_483_648 — used when doctor
# needs to sum per-cell mem to compare against host capacity.
_UNITS = {"k": 1024, "m": 1024**2, "g": 1024**3, "t": 1024**4}


def parse_mem(spec: str | int | None) -> int | None:
    """Parse a docker-style mem spec into bytes. None → None."""
    if spec is None:
        return None
    if isinstance(spec, int):
        return spec
    s = str(spec).strip().lower()
    if not s:
        return None
    if s[-1] in _UNITS:
        try:
            return int(float(s[:-1]) * _UNITS[s[-1]])
        except ValueError:
            return None
    try:
        return int(s)
    except ValueError:
        return None
