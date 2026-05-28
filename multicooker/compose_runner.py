"""Run one participant or judge cell as a docker compose service.

Lifecycle per cell:
  1. `docker compose -p <project> up -d <service>`  (image must already be built)
  2. Tail container logs to log_dir/<flavor>.{stdout,stderr}.log
     (compose merges stdout+stderr in `docker compose logs`).
  3. Poll exit status. On wall-clock timeout: `docker compose stop -t 10 <service>`
     then `kill` if still alive.
  4. Tear down with `docker compose rm -fsv <service>`.
  5. Tail logs, run runner_common.detect_rate_limit on combined output.

Building the images is the caller's job (cook.py runs
`docker compose -p <project> build` once before launching anything).
"""

from __future__ import annotations

import subprocess
import time
from pathlib import Path

from .runner_common import RunResult, detect_rate_limit, tail


def _docker_compose(cook_dir: Path, project: str, *args: str,
                    check: bool = False, capture: bool = False) -> subprocess.CompletedProcess:
    cmd = ["docker", "compose", "-p", project, "-f", str(cook_dir / "compose.yaml"), *args]
    return subprocess.run(
        cmd,
        check=check,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None,
        text=capture,
    )


def build_images(cook_dir: Path, project: str, services: list[str]) -> None:
    """Build all participant/judge images for this cook."""
    print(f"[compose] building images for {project}: {services}", flush=True)
    res = _docker_compose(
        cook_dir, project, "build", *services,
        capture=False,
    )
    if res.returncode != 0:
        raise RuntimeError(f"docker compose build failed (exit {res.returncode})")


def _tail_logs(cook_dir: Path, project: str, service: str,
               stdout_path: Path) -> subprocess.Popen:
    """Stream `docker compose logs -f <service>` to a file in the background."""
    f = open(stdout_path, "ab")
    proc = subprocess.Popen(
        ["docker", "compose", "-p", project, "-f", str(cook_dir / "compose.yaml"),
         "logs", "-f", "--no-log-prefix", service],
        stdout=f, stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
    )
    return proc


def _container_id(cook_dir: Path, project: str, service: str) -> str:
    res = _docker_compose(cook_dir, project, "ps", "-q", service, capture=True)
    return (res.stdout or "").strip().splitlines()[0] if res.stdout else ""


def _wait_for_exit(cook_dir: Path, project: str, service: str,
                   timeout_s: int) -> tuple[int, bool, bool]:
    """Block until the service container exits or timeout.

    Returns (exit_code, timed_out, oom_killed).
    """
    deadline = time.time() + timeout_s
    cid = _container_id(cook_dir, project, service)
    if not cid:
        # Container went away immediately (build/start failure).
        return 125, False, False
    while True:
        # `docker inspect` is faster than `compose ps` for one container.
        insp = subprocess.run(
            ["docker", "inspect", "-f",
             "{{.State.Status}}|{{.State.ExitCode}}|{{.State.OOMKilled}}", cid],
            capture_output=True, text=True,
        )
        if insp.returncode != 0:
            # Container removed out from under us — assume crash.
            return 137, False, False
        parts = insp.stdout.strip().split("|")
        status = parts[0] if parts else ""
        exit_code = parts[1] if len(parts) > 1 else "1"
        oom = len(parts) > 2 and parts[2].strip().lower() == "true"
        if status not in ("running", "created", "restarting"):
            try:
                return int(exit_code), False, oom
            except ValueError:
                return 1, False, oom
        if time.time() >= deadline:
            print(f"[compose] {service}: timeout {timeout_s}s — stopping container", flush=True)
            _docker_compose(cook_dir, project, "stop", "-t", "10", service)
            return 124, True, False
        time.sleep(2)


def run_cell(
    cook_dir: Path,
    project: str,
    service: str,
    flavor: str,
    log_dir: Path,
    timeout_s: int,
) -> RunResult:
    """Bring up one service, wait for it to finish, return RunResult."""
    log_dir.mkdir(parents=True, exist_ok=True)
    stdout_path = log_dir / f"{flavor}.stdout.log"
    stderr_path = log_dir / f"{flavor}.stderr.log"
    stdout_path.write_bytes(b"")
    stderr_path.write_bytes(b"")

    started = time.time()
    print(f"[compose] {service}: starting", flush=True)
    res_up = _docker_compose(cook_dir, project, "up", "-d", "--no-deps",
                             "--no-build", service, capture=True)
    if res_up.returncode != 0:
        err = (res_up.stderr or "").strip()
        stderr_path.write_text(err)
        return RunResult(
            flavor=flavor, exit_code=res_up.returncode,
            duration_s=time.time() - started, timed_out=False,
            stdout_path=stdout_path, stderr_path=stderr_path,
            rate_limit_evidence=err[:400], start_failed=True,
        )

    log_proc = _tail_logs(cook_dir, project, service, stdout_path)
    try:
        exit_code, timed_out, oom_killed = _wait_for_exit(
            cook_dir, project, service, timeout_s)
    finally:
        try:
            log_proc.terminate()
            log_proc.wait(timeout=5)
        except Exception:                                                   # noqa: BLE001
            log_proc.kill()

    duration = time.time() - started

    # Final teardown — keeps `docker compose ps` clean for the next cell.
    _docker_compose(cook_dir, project, "rm", "-fsv", service)

    combined = tail(stdout_path)
    rl, retry_after, evidence = detect_rate_limit(flavor, combined)
    return RunResult(
        flavor=flavor, exit_code=exit_code, duration_s=duration,
        timed_out=timed_out, stdout_path=stdout_path, stderr_path=stderr_path,
        rate_limited=rl, retry_after_s=retry_after,
        rate_limit_evidence=evidence, oom_killed=oom_killed,
    )


def teardown(cook_dir: Path, project: str) -> None:
    """Bring the whole compose project down. Safe to call multiple times."""
    _docker_compose(cook_dir, project, "down", "-v", "--remove-orphans", capture=True)
