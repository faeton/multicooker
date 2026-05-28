"""Sealed judge inbox must not leak participant identity (doc P0 item 3).

_seal_for_judging used to copy the whole work tree, so PROMPT.txt and
trace.json (which name the flavor/model) ended up in the blind judge input.
This is a pure-filesystem test — no docker.
"""

from __future__ import annotations

import json
from pathlib import Path

from multicooker.cook import _seal_for_judging


def _make_work(cook: Path, name: str, flavor: str) -> None:
    wt = cook / "work" / name
    (wt / "out").mkdir(parents=True)
    (wt / "out" / "RESULT.md").write_text("the actual submission body\n")
    # Identity-bearing host-side files that must NOT be sealed.
    (wt / "PROMPT.txt").write_text(f"You are the {flavor} participant.\n")
    (wt / "trace.json").write_text(json.dumps({
        "name": name, "flavor": flavor, "model": f"{flavor}-pro",
        "status": "ok", "round_num": 1,
    }))


def test_seal_copies_only_out_and_meta(tmp_path: Path):
    cook = tmp_path / "260101-t"
    _make_work(cook, "alice", "claude")

    _seal_for_judging(cook, "alice", exit_class="ok", round_num=1)

    sealed = cook / "judging" / "_inbox" / "alice"
    entries = sorted(p.name for p in sealed.iterdir())
    assert entries == ["meta.json", "out"]
    assert (sealed / "out" / "RESULT.md").read_text().startswith("the actual")

    meta = json.loads((sealed / "meta.json").read_text())
    assert meta["exit_class"] == "ok"
    assert meta["round"] == 1
    # meta must not carry identity.
    assert "flavor" not in meta
    assert "model" not in meta
    assert "name" not in meta


def test_no_flavor_string_in_sealed_tree(tmp_path: Path):
    cook = tmp_path / "260101-t"
    _make_work(cook, "alice", "claude")
    _seal_for_judging(cook, "alice", exit_class="ok", round_num=1)

    sealed = cook / "judging" / "_inbox" / "alice"
    for f in sealed.rglob("*"):
        if f.is_file():
            assert "claude" not in f.read_text(), f"flavor leaked into {f}"


def test_seal_derives_meta_from_trace_when_args_omitted(tmp_path: Path):
    """rejudge calls _seal_for_judging with only a name; meta must be read
    host-side from trace.json (which itself is never sealed)."""
    cook = tmp_path / "260101-t"
    _make_work(cook, "alice", "codex")
    _seal_for_judging(cook, "alice")

    sealed = cook / "judging" / "_inbox" / "alice"
    assert not (sealed / "trace.json").exists()
    assert not (sealed / "PROMPT.txt").exists()
    meta = json.loads((sealed / "meta.json").read_text())
    assert meta["exit_class"] == "ok"
    assert meta["round"] == 1
