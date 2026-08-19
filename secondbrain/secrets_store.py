"""Reading, writing and testing the connection secrets.

Keys are never typed into a chat and never committed: they live in
``.streamlit/secrets.toml`` (git-ignored, chmod 600) and are mirrored into the
process environment so they take effect immediately.
"""

from __future__ import annotations

import concurrent.futures
import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

from .config import ROOT, Settings

SECRETS_PATH = ROOT / ".streamlit" / "secrets.toml"

# key -> (label, secret?, help, where to get it)
FIELDS: dict[str, tuple[str, bool, str, str]] = {
    "GEMINI_API_KEY": (
        "Gemini API key",
        True,
        "Extraction and adaptive question writing. NotebookLM itself has no API — "
        "this is the plain Gemini API.",
        "https://aistudio.google.com/apikey",
    ),
    "ANTHROPIC_API_KEY": (
        "Claude API key",
        True,
        "The learning-diagnostic engine: why the knowledge keeps failing.",
        "https://console.anthropic.com/settings/keys",
    ),
    "ANKIWEB_USERNAME": (
        "AnkiWeb e-mail",
        False,
        "Used to sync the hub's collection with your AnkiWeb account.",
        "https://ankiweb.net/account/login",
    ),
    "ANKIWEB_PASSWORD": ("AnkiWeb password", True, "Stored locally only, never sent anywhere else.", ""),
    "GITHUB_TOKEN": (
        "GitHub token (backup)",
        True,
        "Keeps your data alive on a free host. Fine-grained token with Contents: read & write "
        "on one PRIVATE repository.",
        "https://github.com/settings/personal-access-tokens",
    ),
    "GITHUB_REPO": (
        "Backup repository",
        False,
        "owner/name of the private repo that stores the database file.",
        "",
    ),
    "NOTION_TOKEN": (
        "Notion integration token",
        True,
        "Create an internal integration, then share your database with it.",
        "https://www.notion.so/my-integrations",
    ),
    "NOTION_DATABASE_ID": (
        "Notion database ID",
        False,
        "The 32-character id in the database URL.",
        "",
    ),
}


@dataclass
class TestResult:
    ok: bool
    message: str


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------

def read() -> dict[str, str]:
    if not SECRETS_PATH.exists():
        return {}
    try:
        with SECRETS_PATH.open("rb") as fh:
            return {k: str(v) for k, v in tomllib.load(fh).items() if not isinstance(v, dict)}
    except (tomllib.TOMLDecodeError, OSError):
        return {}


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def write(values: dict[str, str]) -> Path:
    """Merge values into secrets.toml (empty strings delete a key)."""
    current = read()
    for key, value in values.items():
        value = (value or "").strip()
        if value:
            current[key] = value
        else:
            current.pop(key, None)

    SECRETS_PATH.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Second Brain connections — written by the Connections page.",
        "# This file is git-ignored. Never commit it, never paste these values into a chat.",
        "",
    ]
    lines += [f'{key} = "{_escape(value)}"' for key, value in sorted(current.items())]
    SECRETS_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    try:
        SECRETS_PATH.chmod(0o600)
    except OSError:
        pass

    apply_to_env(current)
    return SECRETS_PATH


def apply_to_env(values: dict[str, str] | None = None) -> None:
    for key, value in (values if values is not None else read()).items():
        if value:
            os.environ[key] = value
        else:
            os.environ.pop(key, None)


def masked(value: str) -> str:
    if not value:
        return "—"
    if len(value) <= 8:
        return "•" * len(value)
    return f"{value[:4]}{'•' * 6}{value[-4:]}"


# ---------------------------------------------------------------------------
# Connection tests — each one makes the smallest possible real call
# ---------------------------------------------------------------------------

def test_gemini(settings: Settings | None = None) -> TestResult:
    from .llm import LLMError, call_gemini

    s = settings or Settings.load()
    if not s.gemini_api_key:
        return TestResult(False, "No key set.")
    try:
        result = call_gemini('Reply with exactly: {"ok": true}', s, json_mode=True, timeout=20)
        return TestResult(True, f"{s.gemini_model} answered: {result.text.strip()[:60]}")
    except LLMError as exc:
        return TestResult(False, str(exc)[:300])


def test_claude(settings: Settings | None = None) -> TestResult:
    from .llm import LLMError, call_claude

    s = settings or Settings.load()
    if not s.anthropic_api_key:
        return TestResult(False, "No key set.")
    try:
        result = call_claude("Reply with exactly: OK", s, max_tokens=16, timeout=20)
        return TestResult(True, f"{s.claude_model} answered: {result.text.strip()[:60]}")
    except LLMError as exc:
        return TestResult(False, str(exc)[:300])


def test_ankiweb(settings: Settings | None = None) -> TestResult:
    from .ankiweb import AnkiWebBridge, AnkiWebError, library_available

    s = settings or Settings.load()
    if not library_available():
        return TestResult(False, "The `anki` package is not installed.")
    if not (s.ankiweb_username and s.ankiweb_password):
        return TestResult(False, "Username or password missing.")
    bridge = AnkiWebBridge(s)
    try:
        with bridge.open() as col:
            bridge._auth(col)
        return TestResult(True, f"Logged in to AnkiWeb as {s.ankiweb_username}.")
    except AnkiWebError as exc:
        return TestResult(False, str(exc)[:300])
    except Exception as exc:  # noqa: BLE001 - surface anything the backend throws
        return TestResult(False, str(exc)[:300])


def test_notion(settings: Settings | None = None) -> TestResult:
    from .notion import NotionClient, NotionError

    s = settings or Settings.load()
    client = NotionClient(s.notion_token, s.notion_database_id)
    if not client.configured:
        return TestResult(False, "Token or database id missing.")
    try:
        schema = client.database_schema()
        return TestResult(True, f"Database reachable · properties: {', '.join(list(schema)[:6])}")
    except NotionError as exc:
        return TestResult(False, str(exc)[:300])


def test_backup(settings: Settings | None = None) -> TestResult:
    from .backup import BackupError, configured, remote_info

    s = settings or Settings.load()
    if not configured(s):
        return TestResult(False, "No token or repository set.")
    try:
        info = remote_info(s)
    except BackupError as exc:
        return TestResult(False, str(exc)[:300])
    if info.exists:
        return TestResult(True, f"Backup found in {s.backup_repo} ({info.size / 1024:.0f} KB).")
    return TestResult(True, f"Repository reachable — no backup stored yet ({s.backup_repo}).")


def test_anki_connect(settings: Settings | None = None) -> TestResult:
    from .anki import AnkiConnect

    s = settings or Settings.load()
    client = AnkiConnect(s.anki_connect_url, timeout=3)
    return (
        TestResult(True, f"AnkiConnect reachable at {client.url}")
        if client.available()
        else TestResult(False, f"Not reachable at {client.url} (desktop Anki only).")
    )


_RAW_TESTS = {
    "Gemini": test_gemini,
    "Claude": test_claude,
    "AnkiWeb": test_ankiweb,
    "Notion": test_notion,
    "Backup": test_backup,
    "AnkiConnect (desktop)": test_anki_connect,
}

TEST_TIMEOUT = 30


def _bounded(func):
    """Never let a hanging network call freeze the app."""

    def wrapper(settings: Settings | None = None) -> TestResult:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(func, settings)
            try:
                return future.result(timeout=TEST_TIMEOUT)
            except concurrent.futures.TimeoutError:
                return TestResult(False, f"No answer within {TEST_TIMEOUT}s — check the network or the key.")
            except Exception as exc:  # noqa: BLE001
                return TestResult(False, str(exc)[:300])

    return wrapper


TESTS = {name: _bounded(func) for name, func in _RAW_TESTS.items()}


def status(settings: Settings | None = None) -> dict[str, bool]:
    s = settings or Settings.load()
    return {
        "Gemini": bool(s.gemini_api_key),
        "Claude": bool(s.anthropic_api_key),
        "AnkiWeb": bool(s.ankiweb_username and s.ankiweb_password),
        "Notion": bool(s.notion_token and s.notion_database_id),
        "Backup": bool(s.backup_token and s.backup_repo),
    }
