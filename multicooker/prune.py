"""`multicooker prune` — delete cooks older than N days (server-like cleanup).

Distinct from `clean`, which only tears down docker artifacts and never removes
your results. `prune` is destructive: it tears down each stale cook's docker
project (via `clean`) and then deletes the cook directory. `--keep-results`
preserves `summary.json` + `leaderboard.md` (and the folder) so a long-lived
installation keeps the verdicts while reclaiming disk.

A cook's age is taken from `status.json.updated_at` (the contract timestamp,
maintained through every phase), falling back to the newest result-file mtime,
then the directory mtime — so a cook that finished long ago but whose folder was
recently `stat`-touched still reads as old.
"""

from __future__ import annotations

import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from . import state
from .clean import _clean_one

_RESULT_GLOBS = ("status.json", "summary.json", "RUN_RESULT.json",
                 "REFINE_*_RESULT.json", "JUDGE_RESULT.json")
_KEEP_ON_RESULTS = {"summary.json", "leaderboard.md"}


def _age_days(cook_dir: Path, now: datetime) -> float:
    """How many days since this cook was last meaningfully updated."""
    ts = None
    st = state.read_status(cook_dir)
    if st and isinstance(st.get("updated_at"), str):
        try:
            ts = datetime.fromisoformat(st["updated_at"])
        except ValueError:
            ts = None
    if ts is None:
        mtimes: list[float] = []
        for pat in _RESULT_GLOBS:
            for f in cook_dir.glob(pat):
                try:
                    mtimes.append(f.stat().st_mtime)
                except OSError:
                    pass
        epoch = max(mtimes) if mtimes else cook_dir.stat().st_mtime
        ts = datetime.fromtimestamp(epoch, tz=timezone.utc)
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return (now - ts).total_seconds() / 86400.0


def _prune_one(cook_dir: Path, *, keep_results: bool, dry_run: bool) -> None:
    if dry_run:
        action = "keep summary/leaderboard, remove the rest" if keep_results \
            else "remove entire cook dir"
        print(f"  [dry-run] {cook_dir.name}: docker teardown + {action}")
        return
    # Tear down docker first (compose down --rmi local), keep_creds irrelevant
    # since we're deleting the dir anyway.
    _clean_one(cook_dir, dry_run=False, keep_creds=False)
    if keep_results:
        for child in list(cook_dir.iterdir()):
            if child.name in _KEEP_ON_RESULTS:
                continue
            if child.is_dir() and not child.is_symlink():
                shutil.rmtree(child, ignore_errors=True)
            else:
                try:
                    child.unlink()
                except OSError:
                    pass
        print(f"  pruned {cook_dir.name} (kept {sorted(_KEEP_ON_RESULTS)})")
    else:
        shutil.rmtree(cook_dir, ignore_errors=True)
        print(f"  pruned {cook_dir.name}")


def _prune_images(dry_run: bool) -> None:
    """Remove dangling images + builder cache. Not namespace-scoped — per-cook
    images are already removed by each cook's `compose down --rmi local`; this
    reclaims the leftover dangling layers and build cache."""
    cmds = [["docker", "image", "prune", "-f"],
            ["docker", "builder", "prune", "-f"]]
    for cmd in cmds:
        print(f"  {'[dry-run] ' if dry_run else ''}{' '.join(cmd)}")
        if not dry_run:
            subprocess.run(cmd, check=False,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def prune(root: Path, older_than_days: float, keep_results: bool = False,
          dry_run: bool = False, prune_images: bool = False) -> int:
    if not root.exists():
        print(f"prune: {root} does not exist", flush=True)
        return 2
    now = datetime.now(timezone.utc)
    candidates = []
    for d in sorted(root.iterdir()):
        if not d.is_dir() or not (d / "brief.yaml").exists():
            continue
        age = _age_days(d, now)
        if age >= older_than_days:
            candidates.append((d, age))

    if not candidates:
        print(f"prune: no cooks older than {older_than_days} day(s) under {root}")
        if prune_images:
            _prune_images(dry_run)
        return 0

    print(f"prune: {len(candidates)} cook(s) older than {older_than_days} day(s)"
          f"{' [dry-run]' if dry_run else ''}:")
    for d, age in candidates:
        print(f"- {d.name} ({age:.1f}d old)")
        _prune_one(d, keep_results=keep_results, dry_run=dry_run)
    if prune_images:
        _prune_images(dry_run)
    return 0
