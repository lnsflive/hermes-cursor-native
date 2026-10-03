from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CURSOR_DIR = ROOT / "plugin/model-providers/cursor"
BRIDGE_CLIENT = CURSOR_DIR / "cursor_bridge_client.py"
CURSOR_INIT = CURSOR_DIR / "__init__.py"
SDK_AUTH = CURSOR_DIR / "cursor_sdk_auth.py"


@pytest.fixture
def bridge_client_module(monkeypatch):
    """Load the bridge client without requiring a full Hermes installation."""
    package_name = f"_cursor_bridge_client_test_{id(monkeypatch)}"
    package = types.ModuleType(package_name)
    package.__path__ = [str(CURSOR_DIR)]
    monkeypatch.setitem(sys.modules, package_name, package)

    hermes_constants = types.ModuleType("hermes_constants")
    hermes_constants.get_hermes_home = lambda: Path.home()
    monkeypatch.setitem(sys.modules, "hermes_constants", hermes_constants)

    for name in ("openai", "openai.types", "openai.types.chat"):
        stub = types.ModuleType(name)
        stub.__path__ = []
        monkeypatch.setitem(sys.modules, name, stub)
    openai_types = types.ModuleType("openai.types.chat.chat_completion_message_tool_call")
    openai_types.ChatCompletionMessageToolCall = lambda **kwargs: types.SimpleNamespace(**kwargs)
    openai_types.Function = lambda **kwargs: types.SimpleNamespace(**kwargs)
    monkeypatch.setitem(
        sys.modules, "openai.types.chat.chat_completion_message_tool_call", openai_types
    )

    module_name = f"{package_name}.cursor_bridge_client"
    spec = importlib.util.spec_from_file_location(module_name, BRIDGE_CLIENT)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, module_name, module)
    spec.loader.exec_module(module)
    return module


class _FakeTransport:
    def __init__(self, messages):
        self.messages = messages

    def unary(self, _service, method, _payload, **_kwargs):
        return {"agentId": "agent-test"} if method == "CreateAgent" else {}

    def server_stream(self, *_args, **_kwargs):
        return iter(self.messages)


def _make_client(module, monkeypatch, messages):
    client = module.CursorBridgeClient(api_key="test")
    transport = _FakeTransport(messages)
    monkeypatch.setattr(client, "_ensure_bridge", lambda **_kwargs: transport)
    return client


def test_fetch_models_checks_configured_bridge_command() -> None:
    text = CURSOR_INIT.read_text(encoding="utf-8")
    assert "load_bridge_settings" in text
    assert 'resolve_bridge_command(str(settings.get("command")' in text


def test_missing_credentials_message_mentions_supported_login_commands() -> None:
    text = BRIDGE_CLIENT.read_text(encoding="utf-8")
    assert "Run `hermes model` and pick" in text
    assert "Cursor to sign in" in text
    assert "`hermes-cursor-native login`" in text
    assert 'Run `hermes cursor login`' not in text


def test_harness_mode_honors_disabled_builtin_tools() -> None:
    text = BRIDGE_CLIENT.read_text(encoding="utf-8")
    assert 'if self._tool_mode == "loop" and not self._builtin_tools:' not in text
    assert "if not self._builtin_tools:" in text


def test_sdk_auth_timeout_message_mentions_supported_login_commands() -> None:
    text = SDK_AUTH.read_text(encoding="utf-8")
    assert "`hermes model` and pick Cursor to sign in" in text
    assert "`hermes-cursor-native login`" in text
    assert "`hermes cursor login` to try again" not in text


def test_sdk_error_event_detail_is_included_in_bridge_error(
    bridge_client_module, monkeypatch
) -> None:
    client = _make_client(
        bridge_client_module,
        monkeypatch,
        [
            {
                "sdkMessage": {
                    "type": "status",
                    "message": {
                        "type": "status",
                        "status": "ERROR",
                        "errorCode": "ERROR_BAD_MODEL_NAME",
                        "message": (
                            'AI Model Not Found Invalid parameters for registry model: '
                            '"grok-4.7"'
                        ),
                    },
                }
            },
            {"result": {"status": "RUN_LIFECYCLE_STATUS_ERROR"}},
        ],
    )

    with pytest.raises(bridge_client_module.CursorBridgeError) as exc_info:
        client.chat.completions.create(model="grok-4.7", messages=[])

    assert 'Invalid parameters for registry model: "grok-4.7"' in str(exc_info.value)
    assert exc_info.value.code == "ERROR_BAD_MODEL_NAME"


def test_finished_run_still_returns_text(bridge_client_module, monkeypatch) -> None:
    client = _make_client(
        bridge_client_module,
        monkeypatch,
        [{"result": {"status": "RUN_LIFECYCLE_STATUS_FINISHED", "result": {"result": "ok"}}}],
    )

    response = client.chat.completions.create(model="auto", messages=[])

    assert response.choices[0].message.content == "ok"
