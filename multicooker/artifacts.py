"""`cooks/<cook>/artifacts.json` — a visibility-tagged manifest of cook files.

An external control plane needs to know which files are safe to publish. We
walk the cook dir and tag every file with one of four visibility classes:

  public     — safe to post to a chat topic: `leaderboard.md`, `summary.json`,
               each participant's own `out/`, and sanitized judge `review.md`.
  operator   — useful for debugging, not public by default: logs, traces,
               result/status/event files, compose, briefs, raw inputs.
  secret     — credential-bearing: `.auth/`.
  host_only  — must never leave the host: judge de-anonymization mapping,
               the sealed inbox, and judge working copies.

Classification is DENYLIST-FIRST: `secret` and `host_only` are matched before
anything else, and an UNKNOWN path defaults to `operator`, never `public` — a
new file type can't silently become publishable. `archive` consumes these
classes to decide what to copy.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

from . import state
from .runner_common import _DEFAULT_IGNORE

PUBLIC = "public"
OPERATOR = "operator"
SECRET = "secret"
HOST_ONLY = "host_only"

# Files larger than this don't get a sha256 (keeps manifest cheap on big out/).
MAX_HASH_BYTES = 5 * 1024 * 1024

_KIND_BY_SUFFIX = {
    ".md": "markdown", ".json": "json", ".jsonl": "jsonl", ".log": "log",
    ".yaml": "yaml", ".yml": "yaml", ".txt": "text", ".html": "html",
    ".css": "css", ".js": "javascript", ".ts": "typescript", ".py": "python",
}


def artifacts_path(cook_dir: Path) -> Path:
    return cook_dir / "artifacts.json"


def classify(rel: str) -> str:
    """Map a cook-relative POSIX path to a visibility class. Denylist-first."""
    parts = rel.split("/")
    head = parts[0]

    # --- denylist first: secret + host_only win over everything ---
    # `.auth` ANYWHERE in the path is secret — not just at the cook root. A
    # participant could write work/<p>/out/.auth/creds.json, which would
    # otherwise match the public out/ wildcard below and leak.
    if ".auth" in parts:
        return SECRET
    if head == "judging":
        if rel == "judging/_mapping.json":
            return HOST_ONLY
        if len(parts) >= 2:
            sub = parts[1]
            if sub in ("_inbox", "_judge_input") or sub.startswith("_work-"):
                return HOST_ONLY
            # judging/<judge>/review.md is the sanitized, publishable review.
            if not sub.startswith("_") and parts[-1] == "review.md":
                return PUBLIC
        return OPERATOR

    # --- explicit public allowlist ---
    if rel in ("leaderboard.md", "summary.json"):
        return PUBLIC
    # A participant's own canonical submission: work/<p>/out/**
    if head == "work" and len(parts) >= 3 and parts[2] == "out":
        return PUBLIC

    # --- everything else is operator (safe default for unknowns) ---
    return OPERATOR


def _kind(path: Path) -> str:
    return _KIND_BY_SUFFIX.get(path.suffix.lower(), "file")


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def _walk_files(cook_dir: Path):
    """Yield files under cook_dir, pruning build-junk dirs and our own derived
    outputs, and not following symlinked directories (os.walk followlinks=False).

    Pruned at the cook ROOT only (so a participant's own work/<p>/out/archive/
    survives): the `archive`/`.archive-staging` output dirs, the
    `<cook>-archive.tar.gz` tarball, and `artifacts.json` itself — otherwise a
    second run would manifest/re-archive its own previous output recursively.
    """
    root = str(cook_dir)
    skip_root_dirs = {"archive", ".archive-staging"}
    skip_root_files = {artifacts_path(cook_dir).name,
                       f"{cook_dir.name}-archive.tar.gz"}
    for dirpath, dirnames, filenames in os.walk(cook_dir):
        dirnames[:] = [d for d in dirnames if d not in _DEFAULT_IGNORE]
        if dirpath == root:
            dirnames[:] = [d for d in dirnames if d not in skip_root_dirs]
        for fn in filenames:
            if dirpath == root and fn in skip_root_files:
                continue
            yield Path(dirpath) / fn


def build_manifest(cook_dir: Path) -> dict:
    """Walk the cook dir, classify every file, write artifacts.json atomically."""
    entries: list[dict] = []
    for path in _walk_files(cook_dir):
        rel = path.relative_to(cook_dir).as_posix()
        entry: dict = {"path": rel, "kind": _kind(path),
                       "visibility": classify(rel)}
        if path.is_symlink():
            entry["symlink"] = True  # never hashed, never archived
        elif path.is_file():
            try:
                size = path.stat().st_size
            except OSError:
                size = None
            if size is not None:
                entry["size"] = size
                if size <= MAX_HASH_BYTES:
                    entry["sha256"] = _sha256(path)
        else:
            # FIFO / socket / device — list it, but never stat/hash/archive it
            # (hashing a FIFO would block; copying it would error).
            entry["special"] = True
        entries.append(entry)
    entries.sort(key=lambda e: e["path"])
    manifest = {
        "schema_version": 1,
        "cook": cook_dir.name,
        "generated_at": state.now_iso(),
        "artifacts": entries,
    }
    state.write_json_atomic(artifacts_path(cook_dir), manifest)
    return manifest


def artifacts_cmd(name: str, root: Path, as_json: bool = False) -> int:
    """`multicooker artifacts <cook> [--json]` — (re)build + show the manifest."""
    import json

    cook_dir = root / name if not Path(name).is_absolute() else Path(name)
    if not cook_dir.exists():
        print(f"error: cook folder {cook_dir} does not exist", flush=True)
        return 2
    manifest = build_manifest(cook_dir)
    if as_json:
        print(json.dumps(manifest, indent=2))
        return 0
    by_vis: dict[str, int] = {}
    for e in manifest["artifacts"]:
        by_vis[e["visibility"]] = by_vis.get(e["visibility"], 0) + 1
    print(f"[artifacts] {cook_dir.name}: {len(manifest['artifacts'])} file(s)")
    for vis in (PUBLIC, OPERATOR, SECRET, HOST_ONLY):
        if vis in by_vis:
            print(f"  {vis:9} {by_vis[vis]}")
    print(f"[artifacts] written: {artifacts_path(cook_dir)}")
    return 0
