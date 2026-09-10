from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CURSOR_DIR = ROOT / "plugin/model-providers/cursor"


def _load_cursor_module(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(
        f"cursor.{name}",
        CURSOR_DIR / filename,
        submodule_search_locations=[str(CURSOR_DIR)],
    )
    module = importlib.util.module_from_spec(spec)
    module.__package__ = "cursor"
    sys.modules[f"cursor.{name}"] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


cursor_pkg = types.ModuleType("cursor")
cursor_pkg.__path__ = [str(CURSOR_DIR)]  # type: ignore[attr-defined]
sys.modules["cursor"] = cursor_pkg
cursor_sdk_auth = _load_cursor_module("cursor_sdk_auth", "cursor_sdk_auth.py")
cursor_pkg.cursor_sdk_auth = cursor_sdk_auth
setup_flow = _load_cursor_module("setup_flow", "setup_flow.py")


def test_force_new_login_restores_credentials_on_failure(monkeypatch):
    backup = {
        "version": 1,
        "backendUrl": "https://api2.cursor.sh",
        "apiKey": "sk-old",
        "apiKeyExpiresAtMs": 9_999_999_999_000,
        "email": "user@example.com",
    }
    restored: list[dict] = []

    monkeypatch.setattr(cursor_sdk_auth, "read_sdk_credentials", lambda: backup)
    monkeypatch.setattr(cursor_sdk_auth, "clear_sdk_credentials", lambda: True)

    def fail_login(**_kwargs):
        raise RuntimeError("login cancelled")

    def save_sdk_credentials(**kwargs):
        restored.append(kwargs)

    monkeypatch.setattr(cursor_sdk_auth, "login", fail_login)
    monkeypatch.setattr(cursor_sdk_auth, "save_sdk_credentials", save_sdk_credentials)

    with pytest.raises(RuntimeError, match="login cancelled"):
        setup_flow._login_cursor_oauth(force_new_login=True)

    assert restored == [{
        "backend_url": "https://api2.cursor.sh",
        "api_key": "sk-old",
        "api_key_expires_at_ms": 9_999_999_999_000,
        "email": "user@example.com",
    }]


def test_force_new_login_restores_credentials_on_keyboard_interrupt(monkeypatch):
    backup = {
        "version": 1,
        "backendUrl": "https://api2.cursor.sh",
        "apiKey": "sk-old",
        "apiKeyExpiresAtMs": 9_999_999_999_000,
        "email": "user@example.com",
    }
    restored: list[dict] = []

    monkeypatch.setattr(cursor_sdk_auth, "read_sdk_credentials", lambda: backup)
    monkeypatch.setattr(cursor_sdk_auth, "clear_sdk_credentials", lambda: True)
    monkeypatch.setattr(cursor_sdk_auth, "login", lambda **_kwargs: (_ for _ in ()).throw(KeyboardInterrupt()))
    monkeypatch.setattr(cursor_sdk_auth, "save_sdk_credentials", lambda **kwargs: restored.append(kwargs))

    with pytest.raises(KeyboardInterrupt):
        setup_flow._login_cursor_oauth(force_new_login=True)

    assert restored[0]["api_key"] == "sk-old"
