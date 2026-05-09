"""`multivarka doctor` — preflight check for docker-mode prerequisites.

Verifies, before you commit to a long cook, that:
  - docker is installed and the daemon is reachable;
  - `docker compose` v2 is available;
  - subscription creds exist for each requested flavor (claude/codex/gemini)
    in the format the snapshot code expects.

Exits 0 if everything checks out, 1 otherwise. Prints one line per check,
and a concrete remediation for each failure.

Run shapes:
  multivarka doctor                     # check default flavors
  multivarka doctor --participants claude,codex
  multivarka doctor cooks/<task>        # check the flavors that <task> needs
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

from . import creds


def _check_docker() -> tuple[bool, str]:
    try:
        out = subprocess.run(["docker", "version", "--format", "{{.Server.Version}}"],
                             capture_output=True, text=True, timeout=5)
    except FileNotFoundError:
        return False, "`docker` not on PATH. Install Docker Desktop or colima."
    except subprocess.TimeoutExpired:
        return False, "`docker version` hung — daemon not responding. Start Docker."
    if out.returncode != 0:
        msg = (out.stderr or out.stdout).strip().splitlines()[-1] if (out.stderr or out.stdout) else "unknown"
        return False, f"docker daemon unreachable: {msg}. Start Docker Desktop / colima."
    return True, f"docker server v{out.stdout.strip()}"


def _check_compose() -> tuple[bool, str]:
    try:
        out = subprocess.run(["docker", "compose", "version", "--short"],
                             capture_output=True, text=True, timeout=5)
    except FileNotFoundError:
        return False, "`docker compose` (v2) not available. Update Docker."
    if out.returncode != 0:
        return False, f"`docker compose` failed: {(out.stderr or out.stdout).strip()}"
    return True, f"docker compose v{out.stdout.strip()}"


def _check_flavor(flavor: str) -> tuple[bool, str]:
    """Dry-run the snapshot for one flavor into a tempdir; report cleanly."""
    with tempfile.TemporaryDirectory(prefix="mv-doctor-") as td:
        tmp = Path(td)
        try:
            creds.snapshot(tmp, [flavor])
        except creds.CredsError as e:
            # CredsError messages already include path + remediation; clean
            # up the multi-line wrapping for single-flavor display.
            msg = str(e)
            if msg.startswith("creds snapshot failed:"):
                msg = msg.split("\n", 1)[1].lstrip(" -")
            return False, msg
        return True, "creds present"


def doctor(name: str | None, root: Path,
           participants_override: list[str] | None) -> int:
    flavors: list[str]
    if name:
        cook_dir = root / name if not Path(name).is_absolute() else Path(name)
        brief_yaml = cook_dir / "brief.yaml"
        if not brief_yaml.exists():
            print(f"doctor: {brief_yaml} missing — pass --participants instead",
                  file=sys.stderr)
            return 2
        cfg = yaml.safe_load(brief_yaml.read_text())
        flavors = sorted({p.get("flavor", p["name"])
                          for p in cfg.get("participants", [])}
                         | {j.get("flavor", j["name"])
                            for j in cfg.get("judges", [])})
    elif participants_override:
        flavors = sorted(set(participants_override))
    else:
        flavors = ["claude", "codex", "gemini"]

    failed = 0
    print(f"checking docker-mode prerequisites for flavors: {', '.join(flavors)}")
    print()

    for label, fn in [("docker", _check_docker), ("docker compose", _check_compose)]:
        ok, msg = fn()
        marker = "OK " if ok else "FAIL"
        print(f"  [{marker}] {label}: {msg}")
        if not ok:
            failed += 1

    for flavor in flavors:
        ok, msg = _check_flavor(flavor)
        marker = "OK " if ok else "FAIL"
        print(f"  [{marker}] {flavor}: {msg}")
        if not ok:
            failed += 1

    print()
    if failed:
        print(f"doctor: {failed} check(s) failed — fix the FAIL lines above before "
              f"running `cook`.")
        return 1
    print("doctor: all good. ready for `multivarka cook`.")
    return 0
