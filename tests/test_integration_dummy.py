"""End-to-end smoke: full new→cook→judge→report on dummy flavor.

Skipped if docker isn't reachable. Otherwise launches the CLI in a tmp
cooks/ root and verifies the leaderboard exists and contains both
participants. This catches regressions in compose-render, runner,
judging, and report aggregation in one go without burning real LLM creds.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest


def _docker_available() -> bool:
    if shutil.which("docker") is None:
        return False
    res = subprocess.run(["docker", "version", "--format", "{{.Server.Version}}"],
                         capture_output=True, timeout=5)
    return res.returncode == 0


pytestmark = pytest.mark.skipif(
    not _docker_available(),
    reason="docker daemon not reachable; skipping integration smoke",
)


REPO_ROOT = Path(__file__).resolve().parents[1]


def _run(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "multivarka.cli", *args],
        cwd=cwd, capture_output=True, text=True, timeout=300,
    )


def test_full_pipeline_on_dummy(tmp_path: Path):
    root = tmp_path / "cooks"
    # 1. new
    res = _run(["new", "smoke", "--root", str(root),
                "--participants", "a=dummy,b=dummy"], cwd=REPO_ROOT)
    assert res.returncode == 0, res.stderr or res.stdout
    cook_dirs = list(root.iterdir())
    assert len(cook_dirs) == 1
    cook = cook_dirs[0]

    # Replace template judges (claude/gemini) with dummy so we don't need creds.
    import yaml
    brief_yaml = cook / "brief.yaml"
    cfg = yaml.safe_load(brief_yaml.read_text())
    cfg["judges"] = [{"name": "dummy-judge", "flavor": "dummy"}]
    brief_yaml.write_text(yaml.safe_dump(cfg, sort_keys=False))

    # 2. cook
    res = _run(["cook", cook.name, "--root", str(root)], cwd=REPO_ROOT)
    assert res.returncode == 0, res.stderr or res.stdout
    assert (cook / "RUN_RESULT.json").exists()

    # 3. judge
    res = _run(["judge", cook.name, "--root", str(root)], cwd=REPO_ROOT)
    assert res.returncode == 0, res.stderr or res.stdout
    assert (cook / "judging" / "dummy-judge" / "scores.json").exists()

    # 4. report
    res = _run(["report", cook.name, "--root", str(root)], cwd=REPO_ROOT)
    assert res.returncode == 0, res.stderr or res.stdout
    leaderboard = (cook / "leaderboard.md").read_text()
    assert "| a |" in leaderboard
    assert "| b |" in leaderboard
    assert "dummy-judge" in leaderboard

    # Cleanup the docker resources so we don't leak between test runs.
    _run(["clean", cook.name, "--root", str(root)], cwd=REPO_ROOT)
