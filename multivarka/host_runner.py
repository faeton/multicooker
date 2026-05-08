"""Spawn the host-installed CLI for one participant. No Docker. No API keys.

Adapted from the reproxy `arena/coding-sandbox/host_runner.py`. The CLI uses
its own subscription auth (claude → macOS Keychain, codex/gemini → OAuth files
under ~/.<cli>/). Subscriptions throttle: when any of the three CLIs hits a
rate-limit, the orchestrator can either sleep until reset or defer that
participant and proceed with others.

Lessons baked in:
- argv hygiene: `--print <prompt> --add-dir <wt>` for claude (variadic
  --add-dir would otherwise eat the prompt as another path).
- macOS sleep: `caffeinate -dimsu -w <pid>` blocks system sleep while the CLI
  runs; we additionally detect retroactive sleep via wall-vs-monotonic skew.
- Sandbox rules: --dangerously-* flags are ONLY used inside an actual sandbox
  (env MULTIVARKA_IN_SANDBOX=1). On host we use soft auto-accept.
"""

from __future__ import annotations

import os
import re
import shutil
import signal
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass
class RunResult:
    flavor: str
    exit_code: int
    duration_s: float
    timed_out: bool
    stdout_path: Path
    stderr_path: Path
    rate_limited: bool = False
    retry_after_s: int = 0
    rate_limit_evidence: str = ""
    attempts: int = 1


HOST_FLAGS = {
    "claude": ["--permission-mode", "acceptEdits"],
    "codex":  ["--sandbox", "workspace-write", "--skip-git-repo-check"],
    "gemini": ["--yolo"],
}
SANDBOX_FLAGS = {
    "claude": ["--dangerously-skip-permissions"],
    "codex":  ["--dangerously-bypass-approvals-and-sandbox", "--skip-git-repo-check"],
    "gemini": ["--yolo"],
}


def _flags(flavor: str) -> list[str]:
    return SANDBOX_FLAGS[flavor] if os.environ.get("MULTIVARKA_IN_SANDBOX") == "1" else HOST_FLAGS[flavor]


CLI_COMMANDS = {
    "claude": lambda wt, p: [
        # Prompt MUST come before --add-dir: --add-dir is variadic and will
        # otherwise consume the prompt as another path.
        "claude", "--print", *_flags("claude"),
        p,
        "--add-dir", str(wt),
    ],
    "codex": lambda wt, p: [
        "codex", "exec", "--cd", str(wt), *_flags("codex"),
        p,
    ],
    "gemini": lambda wt, p: [
        "gemini", *_flags("gemini"), "-p", p,
    ],
}


DEFAULT_RL_WAIT_S = 2 * 60 * 60 + 15 * 60   # 2h15m
MAX_RL_RETRIES = 1

_RL_PATTERNS = {
    "claude": [
        re.compile(r"5[- ]hour limit reached", re.I),
        re.compile(r"weekly limit reached", re.I),
        re.compile(r"usage limit reached", re.I),
        re.compile(r"hit your limit", re.I),
        re.compile(r"rate.?limit", re.I),
        re.compile(r"resets?\s+(?:at\s+)?(\d{1,2}):(\d{2})\s*(am|pm)?", re.I),
        re.compile(r"please try again later", re.I),
    ],
    "codex": [
        re.compile(r"hit your usage limit", re.I),
        re.compile(r"try again at (\d{1,2}):(\d{2})\s*(am|pm)?", re.I),
        re.compile(r"usage limit", re.I),
        re.compile(r"rate.?limit", re.I),
        re.compile(r"quota.*(exceeded|exhausted)", re.I),
        re.compile(r"plan limit", re.I),
        re.compile(r"too many requests", re.I),
        re.compile(r"resets? in (\d+)\s*(hour|hours|h|minute|minutes|m)", re.I),
    ],
    "gemini": [
        re.compile(r"quota.*(exceeded|exhausted)", re.I),
        re.compile(r"resource.*exhausted", re.I),
        re.compile(r"rate.?limit", re.I),
        re.compile(r"daily.*limit", re.I),
        re.compile(r"retry.after[: ]+(\d+)", re.I),
    ],
}


def _detect_rate_limit(flavor: str, text: str) -> tuple[bool, int, str]:
    rate_limited = False
    evidence = ""
    retry_after = 0
    for pat in _RL_PATTERNS.get(flavor, []):
        m = pat.search(text)
        if not m:
            continue
        if not rate_limited:
            rate_limited = True
            evidence = text[max(0, m.start() - 80): m.end() + 80].replace("\n", " ").strip()
        if retry_after > 0:
            continue
        if m.groups():
            try:
                if pat.pattern.startswith("resets? at") or pat.pattern.startswith("try again at"):
                    hh, mm = int(m.group(1)), int(m.group(2))
                    ampm = (m.group(3) or "").lower()
                    if ampm == "pm" and hh < 12:
                        hh += 12
                    if ampm == "am" and hh == 12:
                        hh = 0
                    now = datetime.now()
                    target = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
                    if target <= now:
                        target = target.replace(day=target.day + 1)
                    retry_after = int((target - now).total_seconds())
                elif "in" in pat.pattern:
                    n = int(m.group(1))
                    unit = (m.group(2) or "m").lower()
                    retry_after = n * (3600 if unit.startswith("h") else 60)
                elif "retry.after" in pat.pattern:
                    retry_after = int(m.group(1))
            except (ValueError, IndexError):
                retry_after = 0
    return rate_limited, retry_after, evidence


def _tail(path: Path, n_bytes: int = 16384) -> str:
    try:
        with open(path, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - n_bytes))
            return f.read().decode("utf-8", errors="replace")
    except FileNotFoundError:
        return ""


def _spawn_once(flavor: str, worktree: Path, prompt_text: str,
                stdout_path: Path, stderr_path: Path,
                timeout_s: int) -> tuple[int, float, bool, bool]:
    argv = CLI_COMMANDS[flavor](worktree, prompt_text)
    env = os.environ.copy()
    env["MULTIVARKA_WORKTREE"] = str(worktree)

    wall_started = time.time()
    mono_started = time.monotonic()
    timed_out = False
    with open(stdout_path, "ab") as so, open(stderr_path, "ab") as se:
        proc = subprocess.Popen(
            argv, cwd=str(worktree), stdout=so, stderr=se, env=env,
            start_new_session=True,
        )
        if shutil.which("caffeinate"):
            subprocess.Popen(
                ["caffeinate", "-dimsu", "-w", str(proc.pid)],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
        deadline = wall_started + timeout_s
        while True:
            try:
                exit_code = proc.wait(timeout=5)
                break
            except subprocess.TimeoutExpired:
                if time.time() >= deadline:
                    timed_out = True
                    os.killpg(proc.pid, signal.SIGTERM)
                    try:
                        exit_code = proc.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        os.killpg(proc.pid, signal.SIGKILL)
                        exit_code = -9
                    break
    wall_dur = time.time() - wall_started
    mono_dur = time.monotonic() - mono_started
    slept_during_run = (wall_dur - mono_dur) > 60
    return exit_code, wall_dur, timed_out, slept_during_run


def run(
    flavor: str,
    worktree: Path,
    prompt_text: str,
    log_dir: Path,
    timeout_s: int = 30 * 60,
    wait_for_reset: bool = False,
    max_retries: int = MAX_RL_RETRIES,
) -> RunResult:
    """Run the participant's CLI on its worktree.

    On rate-limit:
      - wait_for_reset=True : sleep until parsed reset and retry up to max_retries
      - wait_for_reset=False: return rate_limited=True so the orchestrator
        can defer this participant and proceed with others
    """
    if flavor not in CLI_COMMANDS:
        raise ValueError(f"unknown flavor: {flavor}")
    if shutil.which(flavor) is None:
        raise RuntimeError(
            f"{flavor!r} CLI not in PATH — install it or remove it from brief.yaml"
        )
    log_dir.mkdir(parents=True, exist_ok=True)
    stdout_path = log_dir / f"{flavor}.stdout.log"
    stderr_path = log_dir / f"{flavor}.stderr.log"
    stdout_path.write_bytes(b"")
    stderr_path.write_bytes(b"")

    attempts = 0
    total_duration = 0.0
    last_evidence = ""
    last_retry_after = 0
    while True:
        attempts += 1
        exit_code, duration, timed_out, slept = _spawn_once(
            flavor, worktree, prompt_text, stdout_path, stderr_path, timeout_s,
        )
        total_duration += duration
        if slept and attempts <= max_retries:
            print(f"[host_runner] {flavor}: detected system sleep mid-run; retrying", flush=True)
            continue
        combined = _tail(stdout_path) + "\n" + _tail(stderr_path)
        rl, retry_after, evidence = _detect_rate_limit(flavor, combined)
        if not rl:
            return RunResult(
                flavor=flavor, exit_code=exit_code, duration_s=total_duration,
                timed_out=timed_out, stdout_path=stdout_path, stderr_path=stderr_path,
                attempts=attempts,
            )
        last_evidence = evidence
        last_retry_after = retry_after or DEFAULT_RL_WAIT_S
        if not wait_for_reset or attempts > max_retries:
            return RunResult(
                flavor=flavor, exit_code=exit_code, duration_s=total_duration,
                timed_out=timed_out, stdout_path=stdout_path, stderr_path=stderr_path,
                rate_limited=True, retry_after_s=last_retry_after,
                rate_limit_evidence=last_evidence, attempts=attempts,
            )
        deadline = time.time() + last_retry_after
        while time.time() < deadline:
            remaining = int(deadline - time.time())
            print(f"[host_runner] {flavor} rate-limited; sleeping {remaining}s "
                  f"(evidence: {last_evidence[:120]})", flush=True)
            time.sleep(min(300, max(30, remaining)))
