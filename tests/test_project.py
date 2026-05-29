"""Centralized compose project naming + namespace resolution (item 17)."""

from __future__ import annotations

from pathlib import Path

import yaml

from multicooker.project import (
    effective_project,
    project_from_compose,
    project_name,
    resolve_namespace,
)


def test_project_name_no_namespace():
    assert project_name("260101-task") == "mc-260101-task"


def test_project_name_with_namespace():
    assert project_name("260101-task", "zuzoo") == "mc-zuzoo-260101-task"


def test_project_name_lowercases_and_dashes():
    assert project_name("My_Task", "Ns_A") == "mc-ns-a-my-task"


def test_resolve_namespace_cli_wins(monkeypatch):
    monkeypatch.setenv("MULTICOOKER_NAMESPACE", "fromenv")
    assert resolve_namespace("fromcli") == "fromcli"


def test_resolve_namespace_env_fallback(monkeypatch):
    monkeypatch.setenv("MULTICOOKER_NAMESPACE", "fromenv")
    assert resolve_namespace(None) == "fromenv"


def test_resolve_namespace_empty_is_none(monkeypatch):
    monkeypatch.delenv("MULTICOOKER_NAMESPACE", raising=False)
    assert resolve_namespace(None) is None
    assert resolve_namespace("   ") is None


def test_resolve_namespace_explicit_empty_wins_over_env(monkeypatch):
    # An explicit `--namespace ""` means "no namespace" and beats the env.
    monkeypatch.setenv("MULTICOOKER_NAMESPACE", "fromenv")
    assert resolve_namespace("") is None
    assert resolve_namespace("  ") is None


def test_effective_project_explicit_namespace_overrides(tmp_path: Path):
    cook = tmp_path / "260101-task"
    cook.mkdir()
    (cook / "compose.yaml").write_text(yaml.safe_dump({"name": "mc-old-260101-task"}))
    # Explicit namespace wins even over a persisted compose name.
    assert effective_project(cook, "260101-task", "new") == "mc-new-260101-task"


def test_effective_project_sticky_reuses_compose(tmp_path: Path, monkeypatch):
    # No explicit namespace → reuse what the cook already ran under, so a
    # later judge/refine/resume can't orphan namespaced containers.
    monkeypatch.delenv("MULTICOOKER_NAMESPACE", raising=False)
    cook = tmp_path / "260101-task"
    cook.mkdir()
    (cook / "compose.yaml").write_text(yaml.safe_dump({"name": "mc-zuzoo-260101-task"}))
    assert effective_project(cook, "260101-task", None) == "mc-zuzoo-260101-task"


def test_effective_project_first_render_no_compose(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("MULTICOOKER_NAMESPACE", raising=False)
    cook = tmp_path / "260101-task"
    cook.mkdir()
    assert effective_project(cook, "260101-task", None) == "mc-260101-task"


def test_project_from_compose_reads_name(tmp_path: Path):
    cook = tmp_path / "260101-task"
    cook.mkdir()
    (cook / "compose.yaml").write_text(yaml.safe_dump({"name": "mc-zuzoo-260101-task"}))
    assert project_from_compose(cook) == "mc-zuzoo-260101-task"


def test_project_from_compose_fallback_no_file(tmp_path: Path):
    cook = tmp_path / "260101-task"
    cook.mkdir()
    assert project_from_compose(cook) == "mc-260101-task"
    assert project_from_compose(cook, namespace="zuzoo") == "mc-zuzoo-260101-task"
