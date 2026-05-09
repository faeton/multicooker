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

from . import base_images, creds


PKG_ROOT = Path(__file__).resolve().parents[1]
TEMPLATES_PARTICIPANTS = PKG_ROOT / "templates" / "cook" / "participants"


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


def _check_dockerfile(flavor: str, cook_dir: Path | None) -> tuple[bool, str]:
    """Dockerfile must exist either in the cook (if one is given) or in templates."""
    if cook_dir is not None:
        cook_df = cook_dir / "participants" / flavor / "Dockerfile"
        if cook_df.exists():
            return True, f"Dockerfile present at {cook_df.relative_to(cook_dir)}"
    tmpl_df = TEMPLATES_PARTICIPANTS / flavor / "Dockerfile"
    if tmpl_df.exists():
        return True, f"template Dockerfile present at templates/cook/participants/{flavor}/"
    where = (
        f"cooks/<task>/participants/{flavor}/Dockerfile or "
        f"templates/cook/participants/{flavor}/Dockerfile"
    )
    return False, f"no Dockerfile for flavor '{flavor}'. Add {where}."


def _check_base_image(flavor: str) -> tuple[bool, str]:
    """Base image is optional; cook auto-builds it on first run."""
    if not (base_images.template_dir(flavor) / "Dockerfile").exists():
        # No base template means this flavor has a self-contained cook
        # Dockerfile (or no Dockerfile at all — covered by _check_dockerfile).
        return True, "no base template (cook Dockerfile is self-contained)"
    if base_images.is_built(flavor):
        return True, f"{base_images.image_tag(flavor)} present"
    return False, (
        f"{base_images.image_tag(flavor)} not built — cook will build it on "
        f"first run, or run `multivarka build-base {flavor}` now."
    )


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
           participants_override: list[str] | None,
           strict: bool = False) -> int:
    flavors: list[str]
    cook_dir: Path | None = None
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
    warned = 0
    print(f"checking docker-mode prerequisites for flavors: {', '.join(flavors)}")
    if strict:
        print("(--strict: warnings count as failures)")
    print()

    for label, fn in [("docker", _check_docker), ("docker compose", _check_compose)]:
        ok, msg = fn()
        marker = "OK " if ok else "FAIL"
        print(f"  [{marker}] {label}: {msg}")
        if not ok:
            failed += 1

    for flavor in flavors:
        # Dockerfile presence — always blocking (cook will fail on build).
        ok, msg = _check_dockerfile(flavor, cook_dir)
        marker = "OK " if ok else "FAIL"
        print(f"  [{marker}] {flavor} dockerfile: {msg}")
        if not ok:
            failed += 1

        # Base image — warn by default (cook auto-builds), fail under --strict.
        ok, msg = _check_base_image(flavor)
        if ok:
            print(f"  [OK ] {flavor} base image: {msg}")
        else:
            marker = "FAIL" if strict else "WARN"
            print(f"  [{marker}] {flavor} base image: {msg}")
            if strict:
                failed += 1
            else:
                warned += 1

        # Creds — always blocking.
        ok, msg = _check_flavor(flavor)
        marker = "OK " if ok else "FAIL"
        print(f"  [{marker}] {flavor} creds: {msg}")
        if not ok:
            failed += 1

    print()
    if failed:
        print(f"doctor: {failed} check(s) failed — fix the FAIL lines above before "
              f"running `cook`.")
        return 1
    if warned:
        print(f"doctor: ok with {warned} warning(s). Ready for `multivarka cook` "
              f"(missing pieces will be built on first run).")
    else:
        print("doctor: all good. ready for `multivarka cook`.")
    return 0
