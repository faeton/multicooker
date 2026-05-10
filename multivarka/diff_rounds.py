"""`multivarka diff <task> N M [--participants ...]` — round-vs-round diff.

Sanity check that refine actually moved the needle. Compares
`rounds/<N>/<p>/` against `rounds/<M>/<p>/` (or against `work/<p>/out/`
if M is the live round).

We use unified diff via `difflib` for text files and `cmp -s` semantics
for binaries (just report "binary: differs / same"). No git involvement —
rounds are tracked outside any VCS by design.
"""

from __future__ import annotations

import difflib
from pathlib import Path

import yaml


def _round_dir(cook_dir: Path, n: int, participant: str) -> Path | None:
    """Return path holding round-N output for <participant>, or None.

    rounds/<N>/<p>/ for snapshotted rounds; work/<p>/out/ for the live one.
    """
    snap = cook_dir / "rounds" / str(n) / participant
    if snap.is_dir():
        return snap
    # Live round = max(rounds/) + 1, or 1 if rounds/ empty.
    rounds_dir = cook_dir / "rounds"
    nums = sorted(int(d.name) for d in rounds_dir.iterdir()
                  if rounds_dir.exists() and d.is_dir() and d.name.isdigit()) \
        if rounds_dir.exists() else []
    live = (nums[-1] + 1) if nums else 1
    if n == live:
        live_path = cook_dir / "work" / participant / "out"
        if live_path.is_dir():
            return live_path
    return None


def _is_text(path: Path, sniff_bytes: int = 4096) -> bool:
    try:
        chunk = path.read_bytes()[:sniff_bytes]
    except OSError:
        return False
    if b"\x00" in chunk:
        return False
    try:
        chunk.decode("utf-8")
        return True
    except UnicodeDecodeError:
        return False


def _walk_files(root: Path) -> set[Path]:
    return {p.relative_to(root) for p in root.rglob("*") if p.is_file()}


def _diff_one(a_root: Path, b_root: Path, label_n: str, label_m: str) -> int:
    """Print unified diff of all files in a_root vs b_root. Return # changed."""
    a_files = _walk_files(a_root)
    b_files = _walk_files(b_root)
    all_files = sorted(a_files | b_files)
    changed = 0
    for rel in all_files:
        a_path = a_root / rel
        b_path = b_root / rel
        in_a, in_b = a_path.is_file(), b_path.is_file()
        if in_a and not in_b:
            print(f"--- {label_n}/{rel}\n+++ {label_m}/{rel}  (deleted)")
            changed += 1
            continue
        if in_b and not in_a:
            print(f"--- {label_n}/{rel}  (added)\n+++ {label_m}/{rel}")
            changed += 1
            continue
        if not (_is_text(a_path) and _is_text(b_path)):
            if a_path.read_bytes() != b_path.read_bytes():
                print(f"binary differs: {rel}")
                changed += 1
            continue
        a_lines = a_path.read_text(errors="replace").splitlines(keepends=True)
        b_lines = b_path.read_text(errors="replace").splitlines(keepends=True)
        if a_lines == b_lines:
            continue
        changed += 1
        for line in difflib.unified_diff(
            a_lines, b_lines,
            fromfile=f"{label_n}/{rel}",
            tofile=f"{label_m}/{rel}",
            n=3,
        ):
            print(line, end="" if line.endswith("\n") else "\n")
    return changed


def diff_rounds(name: str, root: Path, n: int, m: int,
                participants_override: list[str] | None = None) -> int:
    cook_dir = root / name if not Path(name).is_absolute() else Path(name)
    if not cook_dir.exists():
        print(f"error: cook folder {cook_dir} does not exist")
        return 2
    brief = cook_dir / "brief.yaml"
    if not brief.exists():
        print(f"error: {brief} missing")
        return 2
    cfg = yaml.safe_load(brief.read_text())
    participants = [p["name"] for p in cfg.get("participants", [])]
    if participants_override:
        wanted = set(participants_override)
        participants = [p for p in participants if p in wanted]
    if not participants:
        print("error: no participants selected")
        return 2

    if n == m:
        print(f"warn: N == M == {n}; nothing to diff")
        return 0

    total_changed = 0
    for p in participants:
        a = _round_dir(cook_dir, n, p)
        b = _round_dir(cook_dir, m, p)
        if a is None:
            print(f"# {p}: round {n} not found (no rounds/{n}/{p}/, no live)")
            continue
        if b is None:
            print(f"# {p}: round {m} not found")
            continue
        print(f"\n# === {p}: round {n} → round {m} ===")
        changed = _diff_one(a, b, f"r{n}", f"r{m}")
        if changed == 0:
            print(f"  (no changes between r{n} and r{m})")
        total_changed += changed

    return 0 if total_changed > 0 else 1
