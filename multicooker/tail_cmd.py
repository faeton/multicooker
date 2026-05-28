"""`multicooker tail <cook> [actor]` — stream a cook's cell logs.

Prefixes every line with the actor (and stdout/stderr) so a human or a
control plane can follow progress without knowing the flavor-specific log
filename (logs are written as <flavor>.stdout.log). With no actor, tails
every participant and judge.

Single-threaded poll loop: reads new bytes from each known log file each
cycle, buffers per file until a newline, and prints complete prefixed lines
(so lines never interleave half-way). Starts at byte 0 to replay existing
content, then follows. Stops on Ctrl-C, or — in follow mode — once the cook
reaches a terminal state and there's nothing left to read.
"""

from __future__ import annotations

import time
from pathlib import Path

from . import state

# A cook with no actively-running cell: cook/refine end at SEALED, judging at
# JUDGING (not terminal — keep following), the rest are genuine end states.
_TERMINAL = frozenset({state.SEALED, state.REPORTED, state.CANCELLED, state.FAILED})


def _log_dirs(cook_dir: Path, actor: str | None) -> list[tuple[str, Path]]:
    """(actor_name, dir) pairs for participant + judge log directories."""
    pairs: list[tuple[str, Path]] = []
    logs = cook_dir / "logs"
    if logs.is_dir():
        for d in sorted(logs.iterdir()):
            if d.is_dir() and (actor is None or d.name == actor):
                pairs.append((d.name, d))
    jlogs = cook_dir / "judging" / "_logs"
    if jlogs.is_dir():
        for d in sorted(jlogs.iterdir()):
            if d.is_dir() and (actor is None or d.name == actor):
                pairs.append((d.name, d))
    return pairs


def _discover_files(cook_dir: Path, actor: str | None) -> dict[Path, str]:
    """Map each log file path → display prefix (actor/stream)."""
    out: dict[Path, str] = {}
    for actor_name, d in _log_dirs(cook_dir, actor):
        for f in sorted(d.glob("*.log")):
            stream = "stderr" if f.name.endswith(".stderr.log") else "stdout"
            out[f] = f"{actor_name}/{stream}"
    return out


def tail_cmd(name: str, root: Path, actor: str | None = None,
             follow: bool = True, poll_s: float = 0.5) -> int:
    cook_dir = root / name if not Path(name).is_absolute() else Path(name)
    if not cook_dir.exists():
        print(f"error: cook folder {cook_dir} does not exist", flush=True)
        return 2

    handles: dict[Path, "object"] = {}
    buffers: dict[Path, bytes] = {}
    prefixes: dict[Path, str] = {}

    def _pump() -> bool:
        """Read + print any new complete lines. Returns True if it printed."""
        printed = False
        for path, prefix in _discover_files(cook_dir, actor).items():
            prefixes[path] = prefix
            fh = handles.get(path)
            if fh is None:
                try:
                    fh = open(path, "rb")
                except FileNotFoundError:
                    continue
                handles[path] = fh
                buffers[path] = b""
            # Detect truncation (run_cell zeroes the log at start of a cell).
            try:
                if path.stat().st_size < fh.tell():
                    fh.seek(0)
                    buffers[path] = b""
            except OSError:
                pass
            chunk = fh.read()
            if not chunk:
                continue
            data = buffers[path] + chunk
            *lines, rest = data.split(b"\n")
            buffers[path] = rest
            for line in lines:
                print(f"{prefix} | {line.decode('utf-8', 'replace')}", flush=True)
                printed = True
        return printed

    try:
        _pump()
        if not follow:
            return 0
        while True:
            printed = _pump()
            st = state.read_status(cook_dir)
            terminal = bool(st and st.get("state") in _TERMINAL)
            if terminal and not printed:
                # Drain once more, then stop.
                _pump()
                break
            time.sleep(poll_s)
    except KeyboardInterrupt:
        print("", flush=True)
    finally:
        for fh in handles.values():
            try:
                fh.close()
            except OSError:
                pass
    return 0
