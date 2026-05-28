"""Machine-readable control-plane contract for a cook.

Writes machine-facing files under cooks/<name>/ so an external orchestrator
(e.g. Zuzoo) can drive multicooker without scraping stdout or parsing
leaderboard.md:

  status.json   — complete point-in-time snapshot, atomically replaced
  events.jsonl  — append-only event log (one JSON object per line)
  summary.json  — terminal machine-readable result (written by `report`)

Cross-process safety: `cook`, `judge`, `report`, `status`, and `cancel` are
separate OS processes, so an in-process ``threading.Lock`` is not enough. Every
status read-modify-write and every event append takes an advisory ``flock`` on a
dedicated lock file (``<cook>/.mc-lock``). The data files themselves are never
locked: status.json is replaced atomically (temp + fsync + ``os.replace``) and
events.jsonl is appended with a single ``O_APPEND`` ``os.write`` while the lock
is held (a buffered ``open("a").write()`` can split into several ``write(2)``
calls and interleave under concurrency, so we avoid it).
"""

from __future__ import annotations

import fcntl
import json
import os
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_VERSION = 1

# Cook-level lifecycle states.
CREATED = "created"
PREFLIGHTING = "preflighting"
BUILDING = "building"
COOKING = "cooking"
SEALED = "sealed"
JUDGING = "judging"
REPORTED = "reported"
CANCELLED = "cancelled"
FAILED = "failed"

# Cell-level states.
PENDING = "pending"
STARTING = "starting"
RUNNING = "running"
OK = "ok"
RATE_LIMITED = "rate_limited"
TIMED_OUT = "timed_out"
CELL_CANCELLED = "cancelled"
START_FAILED = "start_failed"
OOM_KILLED = "oom_killed"
NON_ZERO_EXIT = "non_zero_exit"
ARTIFACT_MISSING = "artifact_missing"

# Cell states from which `resume` may legitimately retry a participant.
RETRYABLE_CELL_STATES = frozenset(
    {RATE_LIMITED, TIMED_OUT, START_FAILED, NON_ZERO_EXIT}
)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def status_path(cook_dir: Path) -> Path:
    return cook_dir / "status.json"


def events_path(cook_dir: Path) -> Path:
    return cook_dir / "events.jsonl"


def summary_path(cook_dir: Path) -> Path:
    return cook_dir / "summary.json"


def _lock_path(cook_dir: Path) -> Path:
    return cook_dir / ".mc-lock"


@contextmanager
def _locked(cook_dir: Path):
    """Hold an exclusive advisory lock on <cook>/.mc-lock for the body."""
    cook_dir.mkdir(parents=True, exist_ok=True)
    lf = open(_lock_path(cook_dir), "w")
    try:
        fcntl.flock(lf.fileno(), fcntl.LOCK_EX)
        yield
    finally:
        try:
            fcntl.flock(lf.fileno(), fcntl.LOCK_UN)
        finally:
            lf.close()


def write_json_atomic(path: Path, obj) -> None:
    """Serialize obj to path via temp file + fsync + os.replace (POSIX-atomic).

    Public so the legacy *_RESULT.json writers can stop using bare write_text()
    and never leave a half-written file for a concurrent reader (e.g. `report`
    racing an in-progress `refine`).
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(obj, indent=2)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def read_status(cook_dir: Path) -> dict | None:
    """Read status.json. Returns None if absent or unreadable/half-written."""
    p = status_path(cook_dir)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def init_status(cook_dir: Path, cook: str, phase: str, state: str,
                cells: dict | None = None, round_num: int = 1) -> dict:
    """Create/replace status.json with a fresh snapshot."""
    with _locked(cook_dir):
        st = {
            "schema_version": SCHEMA_VERSION,
            "cook": cook,
            "phase": phase,
            "state": state,
            "round": round_num,
            "updated_at": now_iso(),
            "cells": cells or {},
        }
        write_json_atomic(status_path(cook_dir), st)
    return st


def update_status(cook_dir: Path, **changes) -> dict:
    """Read-modify-write top-level status fields (not individual cells)."""
    with _locked(cook_dir):
        st = read_status(cook_dir) or {
            "schema_version": SCHEMA_VERSION, "cells": {},
        }
        st.update(changes)
        st["updated_at"] = now_iso()
        write_json_atomic(status_path(cook_dir), st)
        return st


def set_cell(cook_dir: Path, name: str, *, role: str | None = None,
             flavor: str | None = None, state: str | None = None,
             **fields) -> dict:
    """Merge a cell's role/flavor/state/extra-fields into status.json.

    status.json is host-side only (never shipped to judges), so recording cell
    flavor here does not leak identity the way the sealed inbox would.
    """
    with _locked(cook_dir):
        st = read_status(cook_dir) or {
            "schema_version": SCHEMA_VERSION, "cells": {},
        }
        cells = st.setdefault("cells", {})
        cell = cells.setdefault(name, {})
        if role is not None:
            cell["role"] = role
        if flavor is not None:
            cell["flavor"] = flavor
        if state is not None:
            cell["state"] = state
        for k, v in fields.items():
            cell[k] = v
        st["updated_at"] = now_iso()
        write_json_atomic(status_path(cook_dir), st)
        return st


def append_event(cook_dir: Path, event: str, *, cook: str | None = None,
                 phase: str | None = None, actor: str | None = None,
                 payload: dict | None = None) -> None:
    """Append one event object as a line to events.jsonl (atomic per line)."""
    line: dict = {"ts": now_iso(), "event": event}
    if cook is not None:
        line["cook"] = cook
    if phase is not None:
        line["phase"] = phase
    if actor is not None:
        line["actor"] = actor
    if payload is not None:
        line["payload"] = payload
    data = (json.dumps(line) + "\n").encode("utf-8")
    cook_dir.mkdir(parents=True, exist_ok=True)
    with _locked(cook_dir):
        fd = os.open(str(events_path(cook_dir)),
                     os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
        try:
            os.write(fd, data)
            os.fsync(fd)
        finally:
            os.close(fd)
