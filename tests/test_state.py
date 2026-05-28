"""Unit tests for the machine-readable contract primitives in state.py.

No docker: these exercise the atomic writer, status read-modify-write, and
the events.jsonl append path directly.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path

from multicooker import state


def test_atomic_write_replaces_and_parses(tmp_path: Path):
    p = tmp_path / "x.json"
    state.write_json_atomic(p, {"a": 1})
    state.write_json_atomic(p, {"a": 2, "b": [1, 2, 3]})
    assert json.loads(p.read_text()) == {"a": 2, "b": [1, 2, 3]}
    # No temp files left behind.
    leftovers = [f for f in tmp_path.iterdir() if f.name.startswith(".x.json")]
    assert leftovers == []


def test_init_and_update_status(tmp_path: Path):
    state.init_status(tmp_path, cook="260101-t", phase="cook",
                      state=state.CREATED,
                      cells={"a": {"role": "participant", "state": state.PENDING}})
    st = state.read_status(tmp_path)
    assert st["cook"] == "260101-t"
    assert st["state"] == state.CREATED
    assert st["cells"]["a"]["state"] == state.PENDING

    state.update_status(tmp_path, state=state.COOKING)
    st = state.read_status(tmp_path)
    assert st["state"] == state.COOKING
    # update_status must not clobber cells.
    assert "a" in st["cells"]


def test_set_cell_merges_fields(tmp_path: Path):
    state.init_status(tmp_path, cook="c", phase="cook", state=state.COOKING)
    state.set_cell(tmp_path, "a", role="participant", flavor="claude",
                   state=state.RUNNING, started_at="t0")
    state.set_cell(tmp_path, "a", state=state.OK, duration_s=1.2,
                   exit_class=state.OK)
    cell = state.read_status(tmp_path)["cells"]["a"]
    assert cell["role"] == "participant"
    assert cell["flavor"] == "claude"
    assert cell["state"] == state.OK
    assert cell["started_at"] == "t0"
    assert cell["duration_s"] == 1.2


def test_read_status_missing_returns_none(tmp_path: Path):
    assert state.read_status(tmp_path) is None


def test_append_event_one_object_per_line(tmp_path: Path):
    state.append_event(tmp_path, "cook.created", cook="c", phase="cook")
    state.append_event(tmp_path, "cell.exited", actor="a",
                       payload={"exit_class": "ok"})
    lines = state.events_path(tmp_path).read_text().splitlines()
    assert len(lines) == 2
    first = json.loads(lines[0])
    second = json.loads(lines[1])
    assert first["event"] == "cook.created"
    assert second["actor"] == "a"
    assert second["payload"]["exit_class"] == "ok"
    assert "ts" in first


def test_concurrent_set_cell_no_lost_updates(tmp_path: Path):
    """Each thread writes its own cell; flock must serialize read-modify-write
    so no cell is dropped by an interleaved overwrite."""
    state.init_status(tmp_path, cook="c", phase="cook", state=state.COOKING)
    names = [f"cell{i}" for i in range(20)]

    def worker(n: str):
        state.set_cell(tmp_path, n, role="participant", state=state.OK)

    threads = [threading.Thread(target=worker, args=(n,)) for n in names]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    cells = state.read_status(tmp_path)["cells"]
    assert set(cells) == set(names)


def test_reset_cell_drops_stale_fields(tmp_path: Path):
    state.init_status(tmp_path, cook="c", phase="cook", state=state.COOKING)
    state.set_cell(tmp_path, "a", role="participant", flavor="claude",
                   state=state.RATE_LIMITED, finished_at="t1",
                   exit_class=state.RATE_LIMITED, duration_s=3.0)
    state.reset_cell(tmp_path, "a")
    cell = state.read_status(tmp_path)["cells"]["a"]
    assert cell["state"] == state.PENDING
    assert cell["role"] == "participant"  # preserved
    assert cell["flavor"] == "claude"     # preserved
    assert "finished_at" not in cell
    assert "exit_class" not in cell
    assert "duration_s" not in cell


def test_cancel_marker_lifecycle(tmp_path: Path):
    assert state.is_cancelled(tmp_path) is False
    state.request_cancel(tmp_path)
    assert state.is_cancelled(tmp_path) is True
    state.clear_cancel(tmp_path)
    assert state.is_cancelled(tmp_path) is False
    # clear is idempotent.
    state.clear_cancel(tmp_path)


def test_finalize_honors_cancel_marker(tmp_path: Path):
    state.init_status(tmp_path, cook="c", phase="cook", state=state.COOKING)
    # No marker → sealed.
    assert state.finalize(tmp_path, state.SEALED) == state.SEALED
    assert state.read_status(tmp_path)["state"] == state.SEALED
    # Marker present → cancelled, even though we asked for sealed.
    state.request_cancel(tmp_path)
    assert state.finalize(tmp_path, state.SEALED) == state.CANCELLED
    assert state.read_status(tmp_path)["state"] == state.CANCELLED


def test_concurrent_append_event_no_truncation(tmp_path: Path):
    def worker(i: int):
        state.append_event(tmp_path, "tick", actor=f"a{i}", payload={"i": i})

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(50)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    lines = state.events_path(tmp_path).read_text().splitlines()
    assert len(lines) == 50
    # Every line is independently valid JSON (no interleaved/torn writes).
    seen = {json.loads(ln)["payload"]["i"] for ln in lines}
    assert seen == set(range(50))
