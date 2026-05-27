"""Coverage for host_profile: tier picker, override precedence, mem parser.

We never call real `docker info` in tests — we monkeypatch
`host_profile.docker_info` to return a fixture so the tests stay
hermetic and fast.
"""

from __future__ import annotations

import pytest

from multicooker import host_profile


def _info(mem_gib: float, ncpu: int = 4) -> dict:
    return {
        "MemTotal": int(mem_gib * 1024 ** 3),
        "NCPU": ncpu,
        "ServerVersion": "29.0.0",
        "DockerRootDir": "/var/lib/docker",
    }


def test_tier_from_mem_thresholds() -> None:
    assert host_profile.tier_from_mem(64) == "large"
    assert host_profile.tier_from_mem(32) == "large"
    assert host_profile.tier_from_mem(16) == "medium"
    assert host_profile.tier_from_mem(8) == "medium"
    assert host_profile.tier_from_mem(4) == "small"
    assert host_profile.tier_from_mem(0.5) == "small"


def test_auto_picks_medium_for_11g_vps(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(host_profile, "docker_info", lambda: _info(11))
    p = host_profile.resolve_profile()
    assert p["tier"] == "medium"
    assert p["mem_limit"] == "2g"
    assert p["cpus"] == "1.0"
    assert p["source"] == "auto"


def test_auto_picks_large_for_64g_laptop_no_limits(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(host_profile, "docker_info", lambda: _info(64, 16))
    p = host_profile.resolve_profile()
    assert p["tier"] == "large"
    assert p["mem_limit"] is None
    assert p["cpus"] is None


def test_cli_override_beats_auto(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(host_profile, "docker_info", lambda: _info(64))
    p = host_profile.resolve_profile(cli_override="small")
    assert p["tier"] == "small"
    assert p["mem_limit"] == "1g"
    assert p["source"] == "cli:--profile"


def test_brief_override_beats_cli(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(host_profile, "docker_info", lambda: _info(64))
    p = host_profile.resolve_profile(cli_override="medium", cfg_override="small")
    assert p["tier"] == "small"
    assert p["source"] == "brief:resources.profile"


def test_env_var_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(host_profile, "docker_info", lambda: _info(64))
    monkeypatch.setenv("MULTICOOKER_PROFILE", "small")
    p = host_profile.resolve_profile()
    assert p["tier"] == "small"
    assert p["source"] == "env:MULTICOOKER_PROFILE"


def test_no_docker_falls_back_to_medium(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(host_profile, "docker_info", lambda: None)
    p = host_profile.resolve_profile()
    # Conservative default when we can't see the host.
    assert p["tier"] == "medium"
    assert p["source"] == "auto:no-docker"


def test_parse_mem_suffixes() -> None:
    assert host_profile.parse_mem("512m") == 512 * 1024**2
    assert host_profile.parse_mem("2g") == 2 * 1024**3
    assert host_profile.parse_mem("1.5g") == int(1.5 * 1024**3)
    assert host_profile.parse_mem("2048") == 2048
    assert host_profile.parse_mem(1024) == 1024
    assert host_profile.parse_mem(None) is None
    assert host_profile.parse_mem("garbage") is None
    assert host_profile.parse_mem("") is None
