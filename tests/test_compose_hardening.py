"""render_compose emits the non-negotiable sandbox baseline on every cell,
and never emits anything that would loosen Docker's default seccomp profile.

This is the regression guard for the CVE-2026-31431 (AF_ALG / "Copy Fail")
hardening: the moment a service grows `security_opt: seccomp=unconfined`,
`privileged: true`, or a `cap_add`, the container can create AF_ALG sockets
again. These tests fail loudly if that ever happens.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from multicooker import compose_render, host_profile


def _stub_docker(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(host_profile, "docker_info", lambda: {
        "MemTotal": 11 * 1024 ** 3,
        "NCPU": 4,
        "ServerVersion": "29.0.0",
        "DockerRootDir": "/var/lib/docker",
    })


def _render(tmp_path: Path) -> dict:
    cd = tmp_path / "cook"
    for p in ("alice", "bob"):
        (cd / f"work/{p}/out").mkdir(parents=True)
    (cd / "judging/_work-eve").mkdir(parents=True)
    cfg = {
        "name": "smoke",
        "participants": [
            {"name": "alice", "flavor": "claude"},
            {"name": "bob", "flavor": "codex"},
        ],
        "judges": [{"name": "eve", "flavor": "claude"}],
    }
    out = compose_render.render_compose(cd, cfg)
    return yaml.safe_load(out.read_text())


def test_every_cell_gets_the_hardening_baseline(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _stub_docker(monkeypatch)
    services = _render(tmp_path)["services"]
    # participants and judges alike
    assert set(services) == {
        "participant-alice", "participant-bob", "judge-eve"}
    for name, svc in services.items():
        assert svc["cap_drop"] == ["ALL"], name
        assert svc["security_opt"] == ["no-new-privileges:true"], name
        assert svc["user"] == "1000:1000", name


def test_no_cell_loosens_the_sandbox(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _stub_docker(monkeypatch)
    services = _render(tmp_path)["services"]
    for name, svc in services.items():
        # The load-bearing rule: never disable seccomp, never gain caps or
        # host namespaces.
        assert "cap_add" not in svc, name
        assert not svc.get("privileged"), name
        assert svc.get("pid") != "host", name
        assert svc.get("network_mode") != "host", name
        for opt in svc.get("security_opt", []):
            assert "seccomp=unconfined" not in opt, name
            assert "apparmor=unconfined" not in opt, name
