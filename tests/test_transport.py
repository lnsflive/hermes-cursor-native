from __future__ import annotations

import importlib.util
import json
import struct
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import ModuleType

import pytest


@pytest.fixture
def transport(monkeypatch):
    constants = ModuleType("hermes_constants")
    constants.get_hermes_home = lambda: Path.home() / ".hermes"
    monkeypatch.setitem(sys.modules, "hermes_constants", constants)
    path = Path(__file__).resolve().parents[1] / (
        "plugin/model-providers/cursor/cursor_bridge_transport.py"
    )
    spec = importlib.util.spec_from_file_location("deadline_transport", path)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def bridge_server():
    servers = []

    def start(mode):
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                self.rfile.read(int(self.headers["Content-Length"]))
                if mode == "headers":
                    time.sleep(1)
                self.send_response(200)
                self.end_headers()
                if mode == "stall":
                    time.sleep(1)
                    return
                payload = json.dumps({"message": "ok"}).encode()
                frames = struct.pack(">BI", 0, len(payload)) + payload
                frames += struct.pack(">BI", 2, 2) + b"{}"
                try:
                    for byte in frames:
                        self.wfile.write(bytes([byte]))
                        self.wfile.flush()
                        time.sleep(0.04 if mode == "drip" else 0.001)
                except OSError:
                    pass

            def log_message(self, *args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever,
                                  kwargs={"poll_interval": 0.01}, daemon=True)
        thread.start()
        servers.append((server, thread))
        return f"http://127.0.0.1:{server.server_port}"

    yield start
    for server, thread in servers:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


@pytest.mark.parametrize("mode", ["headers", "stall", "drip"])
def test_deadline_bounds_blocking_open_and_partial_reads(transport, bridge_server, mode):
    client = transport.ConnectJsonTransport(bridge_server(mode), "test")
    started = time.monotonic()
    with pytest.raises(transport.CursorBridgeError, match="timed out|deadline exceeded"):
        list(client.server_stream("Agent", "Run", {}, read_timeout=2, deadline=started + 0.2))
    assert time.monotonic() - started < 0.8


def test_partial_frames_complete_before_deadline(transport, bridge_server):
    client = transport.ConnectJsonTransport(bridge_server("success"), "test")
    assert list(client.server_stream("Agent", "Run", {}, deadline=time.monotonic() + 2)) == [
        {"message": "ok"},
    ]


def test_expired_deadline_does_not_open_connection(transport, monkeypatch):
    def unexpected(*args, **kwargs):
        pytest.fail("Expired stream must not open a connection")

    monkeypatch.setattr(transport.urllib.request, "urlopen", unexpected)
    client = transport.ConnectJsonTransport("http://127.0.0.1:1", "test")
    with pytest.raises(transport.CursorBridgeError, match="deadline exceeded"):
        list(client.server_stream("Agent", "Run", {}, deadline=time.monotonic() - 1))
