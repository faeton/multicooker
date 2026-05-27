"""End-to-end: render_compose emits the right resource limits per profile.

These tests stub `docker info` so they don't depend on the local
docker daemon.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from multicooker import compose_render, host_profile


def _stub_docker(monkeypatch: pytest.MonkeyPatch, mem_gib: float) -> None:
    monkeypatch.setattr(host_profile, "docker_info", lambda: {
        "MemTotal": int(mem_gib * 1024 ** 3),
        "NCPU": 4,
        "ServerVersion": "29.0.0",
        "DockerRootDir": "/var/lib/docker",
    })


def _setup_cook(tmp_path: Path) -> Path:
    cd = tmp_path / "cook"
    for p in ("alice", "bob"):
        (cd / f"work/{p}/out").mkdir(parents=True)
    (cd / "judging/_work-eve").mkdir(parents=True)
    return cd


def _render(cd: Path, **extra) -> dict:
    cfg = {
        "name": "smoke",
        "participants": [
            {"name": "alice", "flavor": "claude"},
            {"name": "bob",   "flavor": "codex"},
        ],
        "judges": [{"name": "eve", "flavor": "claude"}],
        **extra,
    }
    out = compose_render.render_compose(cd, cfg)
    return yaml.safe_load(out.read_text())


def test_medium_profile_emits_2g_caps(monkeypatch: pytest.MonkeyPatch,
                                      tmp_path: Path) -> None:
    _stub_docker(monkeypatch, 11)
    cd = _setup_cook(tmp_path)
    compose = _render(cd)
    svc = compose["services"]["participant-alice"]
    assert svc["mem_limit"] == "2g"
    assert svc["memswap_limit"] == "2g"
    assert svc["cpus"] == "1.0"
    assert svc["pids_limit"] == 512
    assert svc["oom_score_adj"] == 500
    assert svc["ulimits"]["nofile"] == {"soft": 4096, "hard": 8192}
    assert svc["logging"]["driver"] == "json-file"
    assert svc["logging"]["options"]["max-size"] == "10m"


def test_large_profile_emits_no_mem_or_cpus(monkeypatch: pytest.MonkeyPatch,
                                            tmp_path: Path) -> None:
    _stub_docker(monkeypatch, 64)
    cd = _setup_cook(tmp_path)
    compose = _render(cd)
    svc = compose["services"]["participant-alice"]
    # Big-host profile leaves containers uncapped on mem/cpu — but the cheap
    # safeties stay on.
    assert "mem_limit" not in svc
    assert "memswap_limit" not in svc
    assert "cpus" not in svc
    assert svc["pids_limit"] == 512
    assert svc["oom_score_adj"] == 500


def test_per_actor_override_wins(monkeypatch: pytest.MonkeyPatch,
                                 tmp_path: Path) -> None:
    _stub_docker(monkeypatch, 11)
    cd = _setup_cook(tmp_path)
    cfg_extra = {"participants": [
        {"name": "alice", "flavor": "claude",
         "resources": {"mem_limit": "4g", "cpus": 2.0}},
        {"name": "bob",   "flavor": "codex"},
    ]}
    compose = _render(cd, **cfg_extra)
    alice = compose["services"]["participant-alice"]
    bob = compose["services"]["participant-bob"]
    # alice gets the explicit override; bob inherits the medium profile.
    assert alice["mem_limit"] == "4g"
    assert alice["memswap_limit"] == "4g"
    assert alice["cpus"] == "2.0"
    assert bob["mem_limit"] == "2g"
    assert bob["cpus"] == "1.0"


def test_memswap_mirrors_mem_when_only_mem_set(monkeypatch: pytest.MonkeyPatch,
                                               tmp_path: Path) -> None:
    """memswap_limit defaults to 2×mem in docker; we mirror to mem to
    keep a runaway cell out of host swap."""
    _stub_docker(monkeypatch, 11)
    cd = _setup_cook(tmp_path)
    cfg_extra = {"participants": [
        {"name": "alice", "flavor": "claude", "resources": {"mem_limit": "3g"}},
        {"name": "bob",   "flavor": "codex"},
    ]}
    compose = _render(cd, **cfg_extra)
    alice = compose["services"]["participant-alice"]
    assert alice["memswap_limit"] == "3g"


def test_explicit_memswap_respected(monkeypatch: pytest.MonkeyPatch,
                                    tmp_path: Path) -> None:
    _stub_docker(monkeypatch, 11)
    cd = _setup_cook(tmp_path)
    cfg_extra = {"participants": [
        {"name": "alice", "flavor": "claude",
         "resources": {"mem_limit": "2g", "memswap_limit": "3g"}},
        {"name": "bob",   "flavor": "codex"},
    ]}
    compose = _render(cd, **cfg_extra)
    alice = compose["services"]["participant-alice"]
    assert alice["memswap_limit"] == "3g"


def test_cli_override_propagates(monkeypatch: pytest.MonkeyPatch,
                                 tmp_path: Path) -> None:
    _stub_docker(monkeypatch, 64)  # auto would be `large`
    cd = _setup_cook(tmp_path)
    cfg = {"name": "smoke",
           "participants": [{"name": "alice", "flavor": "claude"}],
           "judges": []}
    out = compose_render.render_compose(cd, cfg, profile_override="small")
    svc = yaml.safe_load(out.read_text())["services"]["participant-alice"]
    assert svc["mem_limit"] == "1g"
    assert svc["cpus"] == "0.5"


def test_judge_gets_limits_too(monkeypatch: pytest.MonkeyPatch,
                               tmp_path: Path) -> None:
    _stub_docker(monkeypatch, 11)
    cd = _setup_cook(tmp_path)
    compose = _render(cd)
    judge_svc = compose["services"]["judge-eve"]
    assert judge_svc["mem_limit"] == "2g"
    assert judge_svc["pids_limit"] == 512
