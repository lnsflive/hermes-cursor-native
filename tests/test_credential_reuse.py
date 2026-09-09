from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

SOURCE = Path(__file__).resolve().parents[1] / "plugin/model-providers/cursor/cursor_sdk_auth.py"


@pytest.fixture
def auth(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / ".config"))
    monkeypatch.setenv("APPDATA", str(tmp_path / "AppData/Roaming"))
    monkeypatch.delenv("CURSOR_API_KEY", raising=False)
    spec = importlib.util.spec_from_file_location("cursor_auth_reuse_test", SOURCE)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    return module


def test_cli_key_is_reused_without_copying(auth):
    path = auth.cli_auth_path()
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"apiKey": "test-only-cli-key"}))
    before = path.read_bytes()
    assert auth.resolve_cursor_api_key() == ("test-only-cli-key", "cli_api_key")
    assert path.read_bytes() == before
    assert not auth.sdk_auth_path().exists()


def test_oauth_tokens_are_not_used_as_api_keys(auth):
    path = auth.cli_auth_path()
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"accessToken": "test-access", "refreshToken": "test-refresh"}))
    assert auth.resolve_cursor_api_key() == ("", "")


def test_explicit_key_takes_precedence(auth, monkeypatch):
    path = auth.cli_auth_path()
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"apiKey": "test-cli"}))
    monkeypatch.setenv("CURSOR_API_KEY", "test-explicit")
    assert auth.resolve_cursor_api_key() == ("test-explicit", "env")


@pytest.mark.parametrize("payload", ["invalid json", "[]", '{"apiKey": 123}'])
def test_changed_or_malformed_cli_store_falls_back(auth, payload):
    path = auth.cli_auth_path()
    path.parent.mkdir(parents=True)
    path.write_text(payload)
    assert auth.read_cli_api_key() == ""
