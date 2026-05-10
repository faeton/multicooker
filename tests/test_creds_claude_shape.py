"""Regression test for the macOS Keychain JSON shape used by claude-cli.

The shape has been stable since v0.1 (single top-level key `claudeAiOauth`
containing `accessToken` / `refreshToken` / `expiresAt`). If Anthropic ever
ships a breaking change to the Keychain format, this test will fail loudly
*before* a real cook attempts to use the snapshot — the user gets a
specific error pointing at credential format drift, not a confusing
participant failure deep in the run.

We mock `subprocess.check_output` so this runs cross-platform without
needing an actual Keychain entry.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from multivarka import creds


# Canonical shape as of v0.1 (verified against real keychain entry on macOS,
# see commit history of multivarka/creds.py — `claudeAiOauth` has been the
# top-level key since the file was introduced).
GOOD_BLOB = json.dumps({
    "claudeAiOauth": {
        "accessToken": "sk-ant-oat01-fake",
        "refreshToken": "sk-ant-ort01-fake",
        "expiresAt": 4102444800000,
        "scopes": ["user:inference", "user:profile"],
        "subscriptionType": "pro",
    }
}).encode()


def test_keychain_good_shape_writes_credentials_json(tmp_path: Path) -> None:
    """Happy path: a well-formed keychain blob is written through verbatim."""
    with patch("multivarka.creds.subprocess.check_output", return_value=GOOD_BLOB):
        creds._snapshot_claude_macos(tmp_path)

    out = tmp_path / "claude" / ".credentials.json"
    assert out.exists()
    assert out.stat().st_mode & 0o777 == 0o600
    parsed = json.loads(out.read_bytes())
    assert "claudeAiOauth" in parsed
    assert parsed["claudeAiOauth"]["accessToken"].startswith("sk-ant-oat")


def test_keychain_unexpected_shape_raises(tmp_path: Path) -> None:
    """If Anthropic renames/restructures the top-level key, fail loud."""
    bad = json.dumps({"someNewKey": {"token": "..."}}).encode()
    with patch("multivarka.creds.subprocess.check_output", return_value=bad):
        with pytest.raises(creds.CredsError, match="unexpected shape"):
            creds._snapshot_claude_macos(tmp_path)


def test_keychain_invalid_json_raises(tmp_path: Path) -> None:
    """Garbled blob (e.g. truncated or wrong service) is reported clearly."""
    with patch("multivarka.creds.subprocess.check_output", return_value=b"not json"):
        with pytest.raises(creds.CredsError, match="not valid JSON"):
            creds._snapshot_claude_macos(tmp_path)


def test_keychain_missing_entry_raises(tmp_path: Path) -> None:
    """`security` exits non-zero when the entry isn't there → friendly error."""
    err = subprocess.CalledProcessError(
        returncode=44, cmd=["security"], stderr=b"SecKeychainSearchCopyNext: not found",
    )
    with patch("multivarka.creds.subprocess.check_output", side_effect=err):
        with pytest.raises(creds.CredsError, match="not found"):
            creds._snapshot_claude_macos(tmp_path)
