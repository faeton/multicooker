"""`multicooker archive <cook>` — produce a publishable copy of a cook.

Copies only `public` artifacts by default (add `--include-operator` for logs and
traces). `secret` (`.auth/`) and `host_only` (`_mapping.json`, the sealed
inbox, judge work dirs) are NEVER copied, so the result is safe for a control
plane to post or store. Visibility comes straight from `artifacts.build_manifest`
(rebuilt fresh here so it reflects current state).

Symlinks are skipped, not dereferenced, and every copied file's real path is
verified to stay inside the cook dir — a participant can't smuggle a host secret
into the archive via a symlink in its `out/`.
"""

from __future__ import annotations

import shutil
import tarfile
from pathlib import Path

from . import artifacts


def archive(name: str, root: Path, out: str | None = None,
            include_operator: bool = False, fmt: str = "dir") -> int:
    cook_dir = root / name if not Path(name).is_absolute() else Path(name)
    if not cook_dir.exists():
        print(f"error: cook folder {cook_dir} does not exist", flush=True)
        return 2

    manifest = artifacts.build_manifest(cook_dir)
    allowed = {artifacts.PUBLIC}
    if include_operator:
        allowed.add(artifacts.OPERATOR)

    cook_real = cook_dir.resolve()
    staging = cook_dir / ".archive-staging"
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)

    copied = 0
    skipped = 0
    try:
        for entry in manifest["artifacts"]:
            if entry["visibility"] not in allowed:
                continue
            if entry.get("symlink") or entry.get("special"):
                skipped += 1
                continue
            rel = entry["path"]
            src = cook_dir / rel
            # Copy only real, regular files whose real path stays inside the
            # cook (TOCTOU guard on top of the manifest's symlink marking).
            try:
                if not src.is_file() or src.is_symlink():
                    skipped += 1
                    continue
                if not src.resolve().is_relative_to(cook_real):
                    skipped += 1
                    continue
            except OSError:
                skipped += 1
                continue
            dst = staging / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst, follow_symlinks=False)
            copied += 1

        # Ship a manifest filtered to the included classes so a consumer knows
        # exactly what's inside.
        filtered = dict(manifest)
        filtered["artifacts"] = [
            e for e in manifest["artifacts"]
            if e["visibility"] in allowed and not e.get("symlink")
            and not e.get("special")
        ]
        from . import state
        state.write_json_atomic(staging / "artifacts.json", filtered)

        if fmt == "tar":
            dest = Path(out) if out else cook_dir / f"{cook_dir.name}-archive.tar.gz"
            if dest.exists():
                dest.unlink()
            with tarfile.open(dest, "w:gz") as tf:
                tf.add(staging, arcname=cook_dir.name)
        else:
            dest = Path(out) if out else cook_dir / "archive"
            if dest.exists():
                shutil.rmtree(dest)
            shutil.move(str(staging), str(dest))
    finally:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)

    classes = "public" + (" + operator" if include_operator else "")
    print(f"[archive] {cook_dir.name}: {copied} file(s) ({classes}) → {dest}")
    if skipped:
        print(f"[archive] skipped {skipped} symlink(s)/special/out-of-tree path(s)")
    print("[archive] secret/host_only files were not copied.")
    return 0
