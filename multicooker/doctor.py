"""`multicooker doctor` — preflight check for docker-mode prerequisites.

Verifies, before you commit to a long cook, that:
  - docker is installed and the daemon is reachable;
  - `docker compose` v2 is available;
  - subscription creds exist for each requested flavor (claude/codex/gemini)
    in the format the snapshot code expects.

Exits 0 if everything checks out, 1 otherwise. Prints one line per check,
and a concrete remediation for each failure.

Run shapes:
  multicooker doctor                     # check default flavors
  multicooker doctor --participants claude,codex
  multicooker doctor cooks/<task>        # check the flavors that <task> needs
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

from . import base_images, brief_schema, compose_render, creds, host_profile, lint


TEMPLATES_PARTICIPANTS = (
    Path(__file__).resolve().parent / "templates" / "cook" / "participants"
)

# In-container probe: try to create an AF_ALG socket (the CVE-2026-31431
# "Copy Fail" escape primitive). Docker's default seccomp profile denies the
# socket() call with EPERM, so on a correctly-configured host this raises and
# we exit 0 ("blocked"). If the socket is created, default seccomp is disabled
# or overridden — exit 3 ("allowed"), which is a hard fail. AF_ALG=38,
# SOCK_SEQPACKET=5 (numeric, so the probe doesn't depend on the constant being
# present in the image's Python build).
_AF_ALG_PROBE = (
    "import socket, sys\n"
    "try:\n"
    "    s = socket.socket(38, 5, 0)\n"
    "    s.close()\n"
    "except (PermissionError, OSError):\n"
    "    sys.exit(0)\n"
    "sys.exit(3)\n"
)
_AF_ALG_PROBE_IMAGE = "python:3-alpine"


def _check_docker() -> tuple[bool, str]:
    try:
        out = subprocess.run(["docker", "version", "--format", "{{.Server.Version}}"],
                             capture_output=True, text=True, timeout=5)
    except FileNotFoundError:
        return False, "`docker` not on PATH. Install OrbStack (mac, recommended), Docker Desktop, or colima."
    except subprocess.TimeoutExpired:
        return False, "`docker version` hung — daemon not responding. Start Docker."
    if out.returncode != 0:
        msg = (out.stderr or out.stdout).strip().splitlines()[-1] if (out.stderr or out.stdout) else "unknown"
        return False, f"docker daemon unreachable: {msg}. Start OrbStack / Docker Desktop / colima."
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
        f"first run, or run `multicooker build-base {flavor}` now."
    )


def _check_flavor(flavor: str) -> tuple[bool, str]:
    """Dry-run the snapshot for one flavor into a tempdir; report cleanly."""
    with tempfile.TemporaryDirectory(prefix="mc-doctor-") as td:
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


def _check_af_alg_blocked() -> tuple[str, str]:
    """Probe whether a container can create an AF_ALG socket (CVE-2026-31431).

    Runs a plain `docker run` with no extra flags so it inherits exactly the
    daemon's default posture. Returns (level, message) where level is one of
    "OK" / "WARN" / "FAIL".

    Note: contrary to a common assumption, Docker's *default* seccomp profile
    does NOT reliably block the AF_ALG address family (verified: Docker 29.x /
    OrbStack `profile=builtin` lets socket(AF_ALG) succeed). So:

      - BLOCKED → "OK": something (a stricter seccomp profile, or a host that
        denies it) is denying the socket — the in-container escape primitive is
        gone.
      - ALLOWED → "WARN", not "FAIL": the socket can be created, but whether
        CVE-2026-31431 is exploitable depends on the *host* (patched kernel +
        the algif modprobe block). We can't see that from inside a container,
        so this points you at the host checks (Step C of the hardening plan):
        `uname -r` is patched and `modprobe algif_aead` fails.
    """
    try:
        out = subprocess.run(
            ["docker", "run", "--rm", _AF_ALG_PROBE_IMAGE,
             "python3", "-c", _AF_ALG_PROBE],
            capture_output=True, text=True, timeout=180,
        )
    except FileNotFoundError:
        return "WARN", "`docker` not on PATH — cannot run the AF_ALG probe."
    except subprocess.TimeoutExpired:
        return "WARN", (f"AF_ALG probe timed out (pulling {_AF_ALG_PROBE_IMAGE}?) "
                        "— re-run `multicooker doctor --security`.")
    if out.returncode == 0:
        return "OK ", ("socket(AF_ALG) denied at the container layer "
                       "(CVE-2026-31431 escape primitive blocked).")
    if out.returncode == 3:
        return "WARN", ("socket(AF_ALG) is ALLOWED inside containers — Docker's "
                        "default seccomp does not block it. CVE-2026-31431 then "
                        "depends on the HOST: verify the kernel is patched "
                        "(`uname -r`) and the algif modprobe block is in place "
                        "(`modprobe algif_aead` must fail). Never run with "
                        "seccomp=unconfined / --privileged on top of this.")
    err = (out.stderr or out.stdout).strip()
    last = err.splitlines()[-1] if err else "unknown"
    return "WARN", f"AF_ALG probe inconclusive (exit {out.returncode}): {last}"


def _capacity_check(cfg: dict, profile_override: str | None,
                    concurrent_cooks: int, reserve_mib: int) -> int:
    """Plan host capacity for this cook. Returns 0 if it fits, 1 if not.

    Reads `docker info` from the active docker context — so on a laptop
    with local docker it sees the laptop, and with `DOCKER_HOST=ssh://on1`
    or `docker context use on1` it sees the remote box. We deliberately
    don't shell out to SSH ourselves.

    Sizing: a cook runs participants and judges in *separate phases*
    (cook → judge), so the peak is max(N_p, N_j), not their sum. For
    M concurrent cooks the peak is max × M.
    """
    info = host_profile.docker_info()
    if info is None:
        print("  [WARN] capacity: docker info unavailable — skipping plan")
        return 0
    mem_total_gib = info.get("MemTotal", 0) / (1024 ** 3) if info else 0
    ncpu = info.get("NCPU")
    server = info.get("ServerVersion", "?")
    docker_root = info.get("DockerRootDir", "?")

    top_resources = cfg.get("resources") or {}
    cfg_profile = top_resources.get("profile")
    profile = host_profile.resolve_profile(
        cli_override=profile_override, cfg_override=cfg_profile,
    )
    tier = profile["tier"]

    if profile["mem_limit"] is None:
        # `large` host or explicit large profile — no caps are emitted.
        # Capacity-check would compare nothing against host RAM. Print
        # the picture but pass.
        print(f"  [OK ] capacity: profile={tier} ({profile['source']}), "
              f"host {mem_total_gib:.1f} GiB / {ncpu} vCPU, docker v{server}. "
              f"No per-cell mem_limit emitted (large host); nothing to size.")
        return 0

    # Resolve per-actor limits the same way compose_render will, then
    # take the worst case (the heaviest cell) and multiply by max
    # cells in a single phase × concurrent cooks.
    participants = cfg.get("participants") or []
    judges = cfg.get("judges") or []

    def per_cell_mib(actor: dict) -> int:
        limits = compose_render._resolve_limits(actor, top_resources, profile)
        b = host_profile.parse_mem(limits["mem_limit"])
        return int(b / (1024 ** 2)) if b else 0

    p_mib = [per_cell_mib(p) for p in participants]
    j_mib = [per_cell_mib(j) for j in judges]
    p_phase = sum(p_mib)
    j_phase = sum(j_mib)
    peak_mib = max(p_phase, j_phase)
    needed_mib = peak_mib * max(1, concurrent_cooks)

    # Best-effort host accounting: docker info doesn't expose MemAvailable
    # or SwapTotal in older daemons. Use MemTotal − reserve as a floor.
    available_mib = int(mem_total_gib * 1024) - reserve_mib
    if available_mib < 0:
        available_mib = 0

    heaviest = max(p_mib + j_mib) if (p_mib or j_mib) else 0
    print("  [..] capacity plan:")
    print(f"        host: {mem_total_gib:.1f} GiB / {ncpu} vCPU, docker v{server}")
    print(f"        docker root: {docker_root}")
    print(f"        profile: {tier} ({profile['source']})")
    print(f"        participants phase: {len(participants)} cells × peak "
          f"{heaviest} MiB → {p_phase} MiB")
    print(f"        judges phase:       {len(judges)} cells × peak "
          f"{heaviest} MiB → {j_phase} MiB")
    print(f"        concurrent cooks: {concurrent_cooks}")
    print(f"        required (peak × concurrency): {needed_mib} MiB")
    print(f"        available (MemTotal − {reserve_mib} MiB reserve): "
          f"{available_mib} MiB")

    if needed_mib > available_mib:
        deficit = needed_mib - available_mib
        print(f"  [FAIL] capacity: {deficit} MiB short. Options: "
              f"--profile small, fewer participants/judges, "
              f"--concurrent-cooks 1, or bigger host.")
        return 1
    margin = available_mib - needed_mib
    print(f"  [OK ] capacity: fits with {margin} MiB margin.")
    return 0


def doctor(name: str | None, root: Path,
           participants_override: list[str] | None,
           strict: bool = False,
           capacity: bool = False,
           security: bool = False,
           profile_override: str | None = None,
           concurrent_cooks: int = 1,
           reserve_mib: int = 2048) -> int:
    flavors: list[str]
    cook_dir: Path | None = None
    cfg: dict | None = None
    if name:
        cook_dir = root / name if not Path(name).is_absolute() else Path(name)
        brief_yaml = cook_dir / "brief.yaml"
        if not brief_yaml.exists():
            print(f"doctor: {brief_yaml} missing — pass --participants instead",
                  file=sys.stderr)
            return 2
        cfg = yaml.safe_load(brief_yaml.read_text())
        schema_errors = brief_schema.validate(cfg)
        if schema_errors:
            print(f"doctor: {brief_yaml} is invalid:")
            for e in schema_errors:
                print(f"  - {e}")
            return 1
        for w in brief_schema.validate_warnings(cfg):
            print(f"doctor: warn: {w}")
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

    # Rubric lint (cross-file): only when a cook is given. Cheap, runs before
    # any docker/image work — the plan wants lint to gate expensive operations.
    if cook_dir is not None and cfg is not None:
        for e in lint.lint_consistency(cook_dir, cfg):
            print(f"  [FAIL] rubric lint: {e}")
            failed += 1

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

    if security:
        # Sandbox posture: can a container create the AF_ALG escape primitive
        # (CVE-2026-31431)? "Allowed" is a WARN (host kernel/modprobe is the
        # real barrier, invisible from here), not a hard FAIL — see
        # _check_af_alg_blocked. Under --strict a WARN counts as a failure.
        level, msg = _check_af_alg_blocked()
        print(f"  [{level}] seccomp/AF_ALG: {msg}")
        if level.strip() == "FAIL":
            failed += 1
        elif level.strip() == "WARN":
            warned += 1
            if strict:
                failed += 1

    if capacity:
        if cfg is None:
            print("  [WARN] capacity: no cook given — pass a cook name to size "
                  "per-cell mem against the host")
            warned += 1
        else:
            rc = _capacity_check(cfg, profile_override, concurrent_cooks, reserve_mib)
            if rc != 0:
                failed += 1

    print()
    if failed:
        print(f"doctor: {failed} check(s) failed — fix the FAIL lines above before "
              f"running `cook`.")
        return 1
    if warned:
        print(f"doctor: ok with {warned} warning(s). Ready for `multicooker cook` "
              f"(missing pieces will be built on first run).")
    else:
        print("doctor: all good. ready for `multicooker cook`.")
    return 0
