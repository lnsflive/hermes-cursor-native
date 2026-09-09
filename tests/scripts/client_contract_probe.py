"""Run with stock Hermes python to validate streaming + tool callback contracts."""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[2]
PLUGIN_SRC = REPO_ROOT / "plugin" / "model-providers" / "cursor"
HERMES_SOURCE = (
    Path(sys.argv[1])
    if len(sys.argv) > 1
    else Path(os.getenv("HERMES_AGENT_ROOT", str(Path.home() / ".hermes/hermes-agent")))
)

tmpdir = tempfile.mkdtemp(prefix="hermes-cursor-contract-")
home = Path(tmpdir)
plugin_dest = home / "plugins" / "model-providers" / "cursor"
plugin_dest.parent.mkdir(parents=True, exist_ok=True)
shutil.copytree(PLUGIN_SRC, plugin_dest)

os.environ["HERMES_HOME"] = str(home)
os.environ["HOME"] = str(home)
os.environ["USERPROFILE"] = str(home)
sys.path.insert(0, str(HERMES_SOURCE))

import providers as providers_mod  # noqa: E402

providers_mod._discover_providers()
profile = providers_mod.get_provider_profile("cursor")
if profile is None:
    raise SystemExit("cursor provider not registered")

client = profile.create_client(api_key="test-key", bridge_command="/bin/true")


class FakeTransport:
    def unary(self, service, method, payload, timeout=30.0):
        if service == "SdkAgentService" and method == "CreateAgent":
            return {"agentId": "agent-1"}
        if service == "SdkAgentService" and method == "DeleteAgent":
            return {}
        return {}

    def server_stream(self, service, method, payload, deadline=None):
        yield {
            "result": {
                "status": "RUN_LIFECYCLE_STATUS_FINISHED",
                "result": {"result": "STREAM_OK", "usage": {"inputTokens": 1, "outputTokens": 2}},
            }
        }


client._transport = FakeTransport()
client._process = SimpleNamespace(is_alive=lambda: True, stop=lambda: None)
client._callback_server = SimpleNamespace(
    url="http://127.0.0.1:9", auth_token="t", start=lambda: None, stop=lambda: None
)

import importlib  # noqa: E402

client_module = importlib.import_module(client.__class__.__module__)
with patch.object(client_module, "resolve_bridge_command", return_value="/bin/true"):
    chunks = client.chat.completions.create(
        model="auto",
        messages=[{"role": "user", "content": "Reply STREAM_OK"}],
        stream=True,
    )
assert len(chunks) == 2
assert chunks[0].choices[0].delta.content == "STREAM_OK"

client._active_runs["agent-2"] = client_module._ActiveRun("agent-2", {"terminal"})
response = client._handle_tool_callback(
    {
        "agentId": "agent-2",
        "toolName": "terminal",
        "args": {"command": "echo TOOL_OK"},
        "toolCallId": "call-1",
    }
)
assert response["status"] == "deferred"
class ToolTransport(FakeTransport):
    def server_stream(self, *args, **kwargs):
        run = client._active_runs["agent-1"]
        run.captured_calls.extend([
            {"toolName": "terminal", "args": {"command": "one"}},
            {"toolName": "terminal", "args": {"command": "two"}},
            {"toolName": "terminal", "args": {}, "toolCallId": "supplied-id"},
        ])
        yield {"done": True}


client._transport = ToolTransport()
with patch.object(client_module, "resolve_bridge_command", return_value="/bin/true"):
    completion = client.chat.completions.create(model="auto", messages=[])
calls = completion.choices[0].message.tool_calls
assert len(calls) == 3
assert all(call.id == call.call_id for call in calls)
assert len({call.id for call in calls}) == 3
assert calls[2].id == "supplied-id"
print(json.dumps({"streaming": True, "tool_loop": True}))
