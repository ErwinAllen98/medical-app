"""Free, on-demand persistence for the hub.

The hub can live on a free host (Streamlit Community Cloud), which means no
computer has to stay on — but those hosts have an ephemeral disk: the SQLite
file disappears whenever the app restarts.

So the database is backed up to a GitHub repository through the contents API.
It is small (kilobytes), it is versioned for free, and it only moves when you
press Sync. Use a **private** repository: this file contains your learning data.
"""

from __future__ import annotations

import base64
import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .config import DB_PATH, Settings

API = "https://api.github.com"


class BackupError(RuntimeError):
    pass


@dataclass
class RemoteInfo:
    exists: bool
    sha: str = ""
    size: int = 0
    updated_at: str = ""
    message: str = ""


def _settings(settings: Settings | None = None) -> Settings:
    return settings or Settings.load()


def configured(settings: Settings | None = None) -> bool:
    s = _settings(settings)
    return bool(s.backup_token and s.backup_repo)


def _headers(s: Settings) -> dict:
    return {
        "Authorization": f"Bearer {s.backup_token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _url(s: Settings) -> str:
    return f"{API}/repos/{s.backup_repo}/contents/{s.backup_path}"


def _request(method: str, url: str, s: Settings, **kwargs):
    try:
        import requests
    except ImportError as exc:  # pragma: no cover
        raise BackupError("requests is not installed.") from exc
    try:
        return requests.request(method, url, headers=_headers(s), timeout=60, **kwargs)
    except Exception as exc:
        raise BackupError(f"Could not reach GitHub: {exc}") from exc


def remote_info(settings: Settings | None = None) -> RemoteInfo:
    s = _settings(settings)
    if not configured(s):
        return RemoteInfo(False, message="Backup is not configured.")
    resp = _request("GET", _url(s), s, params={"ref": s.backup_branch})
    if resp.status_code == 404:
        return RemoteInfo(False, message="No backup stored yet.")
    if resp.status_code == 401:
        raise BackupError("GitHub rejected the token (401). Check GITHUB_TOKEN.")
    if resp.status_code >= 400:
        raise BackupError(f"GitHub API {resp.status_code}: {resp.text[:200]}")
    data = resp.json()
    return RemoteInfo(True, sha=data.get("sha", ""), size=int(data.get("size") or 0))


def push(settings: Settings | None = None, db_path: Path | None = None) -> dict:
    """Upload the current database. Returns a small report."""
    s = _settings(settings)
    if not configured(s):
        raise BackupError("Backup is not configured (GITHUB_TOKEN / GITHUB_REPO).")
    path = Path(db_path or DB_PATH)
    if not path.exists():
        raise BackupError("There is no local database to back up yet.")

    payload = path.read_bytes()
    digest = hashlib.sha256(payload).hexdigest()[:12]
    info = remote_info(s)

    body = {
        "message": f"Second Brain backup {datetime.now(timezone.utc):%Y-%m-%d %H:%M} ({digest})",
        "content": base64.b64encode(payload).decode("ascii"),
        "branch": s.backup_branch,
    }
    if info.exists:
        body["sha"] = info.sha

    resp = _request("PUT", _url(s), s, json=body)
    if resp.status_code >= 400:
        raise BackupError(f"Upload failed ({resp.status_code}): {resp.text[:200]}")
    return {"bytes": len(payload), "digest": digest, "repo": s.backup_repo, "path": s.backup_path}


def pull(settings: Settings | None = None, db_path: Path | None = None, overwrite: bool = True) -> dict:
    """Download the stored database over the local one."""
    s = _settings(settings)
    if not configured(s):
        raise BackupError("Backup is not configured.")
    path = Path(db_path or DB_PATH)
    if path.exists() and not overwrite:
        return {"restored": False, "reason": "a local database already exists"}

    resp = _request("GET", _url(s), s, params={"ref": s.backup_branch},
                    headers={**_headers(s), "Accept": "application/vnd.github.raw"})
    if resp.status_code == 404:
        return {"restored": False, "reason": "no backup stored yet"}
    if resp.status_code >= 400:
        raise BackupError(f"Download failed ({resp.status_code}): {resp.text[:200]}")

    payload = resp.content
    if payload[:16] != b"SQLite format 3\x00":
        try:  # the API may still answer with base64 JSON
            payload = base64.b64decode(resp.json().get("content", ""))
        except Exception as exc:
            raise BackupError("The stored file is not a SQLite database.") from exc
    if payload[:16] != b"SQLite format 3\x00":
        raise BackupError("The stored file is not a SQLite database.")

    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.rename(path.with_suffix(".db.local-before-restore"))
    path.write_bytes(payload)
    return {"restored": True, "bytes": len(payload)}


def restore_if_missing(settings: Settings | None = None, db_path: Path | None = None) -> bool:
    """On a fresh (ephemeral) host, bring the database back automatically."""
    path = Path(db_path or DB_PATH)
    if path.exists() and path.stat().st_size > 0:
        return False
    if not configured(settings):
        return False
    try:
        return bool(pull(settings, path, overwrite=True).get("restored"))
    except BackupError:
        return False
