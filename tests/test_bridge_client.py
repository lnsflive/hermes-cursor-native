from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BRIDGE_CLIENT = ROOT / "plugin/model-providers/cursor/cursor_bridge_client.py"


def test_missing_credentials_message_mentions_supported_login_commands() -> None:
    text = BRIDGE_CLIENT.read_text(encoding="utf-8")
    assert "Run `hermes model` and pick" in text
    assert "Cursor to sign in" in text
    assert "`hermes-cursor-native login`" in text
    assert 'Run `hermes cursor login`' not in text
