"""Snapshot subscription creds for the four CLIs into a per-cook .auth/ dir.

Why: docker-mode runs CLIs in Linux containers. Each CLI looks for creds
in a known on-disk location:

  - codex:  ~/.codex/auth.json                   (plain file, OS-agnostic)
  - gemini: ~/.gemini/oauth_creds.json           (plain file, OS-agnostic)
  - claude: ~/.claude/.credentials.json          (Linux), or macOS Keychain
  - grok:   ~/.grok/auth.json                    (plain file, OS-agnostic)

Approach: for each cook, build cooks/<task>/.auth/{claude,codex,gemini}/
with the right files and mode 0600, then bind-mount RO into containers.
We re-snapshot at every cook so token rotations on the host are picked up.

claude-on-macOS quirk: creds live in Keychain entry "Claude Code-credentials"
as a JSON string in the SAME shape Linux expects. We extract via
`security find-generic-password -s "Claude Code-credentials" -w`.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path


KEYCHAIN_SERVICE = "Claude Code-credentials"


class CredsError(RuntimeError):
    pass


def _snapshot_codex(into: Path) -> None:
    src = Path.home() / ".codex" / "auth.json"
    if not src.exists():
        raise CredsError(
            f"codex creds missing at {src}. Run `codex` once on the host to log in."
        )
    dst = into / "codex" / "auth.json"
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    dst.chmod(0o600)


def _snapshot_gemini(into: Path) -> None:
    """Snapshot gemini config dir (oauth_creds.json + settings.json + ids).

    gemini-cli needs settings.json with `security.auth.selectedType:
    "oauth-personal"` plus oauth_creds.json. Bind-mounting only the creds
    file makes the container fall back to demanding GEMINI_API_KEY.
    """
    src = Path.home() / ".gemini"
    if not (src / "oauth_creds.json").exists():
        raise CredsError(
            f"gemini creds missing at {src}/oauth_creds.json. "
            f"Run `gemini` once on the host to log in."
        )
    dst = into / "gemini"
    dst.mkdir(parents=True, exist_ok=True)
    # Copy the small config files; skip history/tmp/state that have no auth bearing.
    for f in ("oauth_creds.json", "settings.json", "google_accounts.json",
              "installation_id", "trustedFolders.json"):
        sf = src / f
        if sf.exists() and sf.is_file():
            shutil.copy2(sf, dst / f)
            (dst / f).chmod(0o600)


def _snapshot_grok(into: Path) -> None:
    src = Path.home() / ".grok" / "auth.json"
    if not src.exists():
        raise CredsError(
            f"grok creds missing at {src}. Run `grok login` on the host first."
        )
    dst = into / "grok" / "auth.json"
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    dst.chmod(0o600)


def _snapshot_claude_macos(into: Path) -> None:
    """Extract Claude Code creds JSON from macOS Keychain."""
    try:
        blob = subprocess.check_output(
            ["security", "find-generic-password", "-s", KEYCHAIN_SERVICE, "-w"],
            stderr=subprocess.PIPE,
        )
    except FileNotFoundError as e:
        raise CredsError("`security` tool not on PATH (need macOS host)") from e
    except subprocess.CalledProcessError as e:
        raise CredsError(
            f"Keychain entry '{KEYCHAIN_SERVICE}' not found. "
            f"Run `claude /login` on the host first.\nstderr: {e.stderr.decode(errors='replace')}"
        ) from e
    try:
        parsed = json.loads(blob)
    except json.JSONDecodeError as e:
        raise CredsError(f"Keychain blob is not valid JSON: {e}")
    if "claudeAiOauth" not in parsed:
        raise CredsError(
            f"Keychain JSON has unexpected shape (keys: {list(parsed.keys())}); "
            f"expected 'claudeAiOauth'. Did the credential format change?"
        )
    dst = into / "claude" / ".credentials.json"
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_bytes(blob)
    dst.chmod(0o600)
    # Pre-create the usage-ledger mountpoint. compose mounts .auth/claude/
    # at /home/node/.claude/:ro and then overlays a writable usage dir at
    # /home/node/.claude/projects/. Docker needs the projects/ entry to
    # exist inside the RO source dir so it has a mountpoint for the
    # writable overlay; otherwise container init fails with
    # "read-only file system" on mkdirat.
    (into / "claude" / "projects").mkdir(exist_ok=True)


def _snapshot_claude_linux(into: Path) -> None:
    src = Path.home() / ".claude" / ".credentials.json"
    if not src.exists():
        raise CredsError(
            f"claude creds missing at {src}. Run `claude /login` on the host first."
        )
    dst = into / "claude" / ".credentials.json"
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    dst.chmod(0o600)
    # See _snapshot_claude_macos for why this empty dir matters.
    (into / "claude" / "projects").mkdir(exist_ok=True)


def snapshot(cook_dir: Path, flavors: list[str]) -> Path:
    """Build cooks/<task>/.auth/ with creds for the requested flavors.

    Returns the .auth root path.
    """
    auth_root = cook_dir / ".auth"
    if auth_root.exists():
        shutil.rmtree(auth_root)
    auth_root.mkdir(parents=True)

    errors: list[str] = []
    for f in sorted(set(flavors)):
        try:
            if f == "codex":
                _snapshot_codex(auth_root)
            elif f == "gemini":
                _snapshot_gemini(auth_root)
            elif f == "grok":
                _snapshot_grok(auth_root)
            elif f == "claude":
                if sys.platform == "darwin":
                    _snapshot_claude_macos(auth_root)
                else:
                    _snapshot_claude_linux(auth_root)
            elif f == "dummy":
                # Dummy flavor needs no creds — used for integration smoke
                # tests without burning subscription credits.
                pass
            else:
                errors.append(f"unknown flavor: {f}")
        except CredsError as e:
            errors.append(f"{f}: {e}")
    if errors:
        raise CredsError("creds snapshot failed:\n  - " + "\n  - ".join(errors))

    # Best-effort .gitignore so .auth/ never gets committed.
    gi = cook_dir / ".gitignore"
    line = ".auth/\n"
    existing = gi.read_text() if gi.exists() else ""
    if line not in existing:
        gi.write_text(existing + (line if existing.endswith("\n") or not existing else "\n" + line))

    return auth_root
