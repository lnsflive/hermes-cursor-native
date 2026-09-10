from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CURSOR_DIR = ROOT / "plugin/model-providers/cursor"
BRIDGE_CLIENT = CURSOR_DIR / "cursor_bridge_client.py"
SDK_AUTH = CURSOR_DIR / "cursor_sdk_auth.py"


def test_missing_credentials_message_mentions_supported_login_commands() -> None:
    text = BRIDGE_CLIENT.read_text(encoding="utf-8")
    assert "Run `hermes model` and pick" in text
    assert "Cursor to sign in" in text
    assert "`hermes-cursor-native login`" in text
    assert 'Run `hermes cursor login`' not in text


def test_sdk_auth_timeout_message_mentions_supported_login_commands() -> None:
    text = SDK_AUTH.read_text(encoding="utf-8")
    assert "`hermes model` and pick Cursor to sign in" in text
    assert "`hermes-cursor-native login`" in text
    assert "`hermes cursor login` to try again" not in text
