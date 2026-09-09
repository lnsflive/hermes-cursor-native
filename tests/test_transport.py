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
                self.send_response(400 if mode == "error" else 200)
                self.end_headers()
                if mode == "stall":
                    time.sleep(1)
                    return
                payload = json.dumps({"message": "ok"}).encode()
                frames = struct.pack(">BI", 0, len(payload)) + payload
                frames += struct.pack(">BI", 2, 2) + b"{}"
                if mode in {"unary", "error"}:
                    frames = payload
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


@pytest.mark.parametrize("mode", ["schema", "token", "silent"])
def test_failed_start_reaps_child(transport, monkeypatch, tmp_path, mode):
    import subprocess

    compat = ModuleType("hermes_cli._subprocess_compat")
    compat.windows_hide_flags = lambda: 0
    monkeypatch.setitem(sys.modules, "hermes_cli._subprocess_compat", compat)
    monkeypatch.setattr(transport, "_build_subprocess_env", lambda _: None)
    payload = {
        "schemaVersion": 9 if mode == "schema" else 1,
        "transport": "tcp", "protocol": "connect", "url": "http://127.0.0.1:1",
        "authTokenFile": str(tmp_path / "missing-token"),
    }
    script = "import time; time.sleep(10)"
    if mode != "silent":
        ready = "cursor-sdk-bridge ready " + json.dumps(payload)
        script = f"print({ready!r}, flush=True); " + script
    popen = subprocess.Popen
    children = []

    def launch(*args, **kwargs):
        # Emit the synthetic ready line on the stderr channel used by the bridge.
        child = popen([sys.executable, "-c", script], stdout=subprocess.PIPE,
                      stderr=subprocess.DEVNULL, text=True)
        child.stderr = child.stdout
        children.append(child)
        return child

    monkeypatch.setattr(transport.subprocess, "Popen", launch)
    bridge = transport.CursorBridgeProcess(command="test", api_key="test", workspace=str(tmp_path))
    started = time.monotonic()
    try:
        with pytest.raises(transport.CursorBridgeError):
            bridge.start(deadline=started + 0.2)
        assert time.monotonic() - started < 0.8
        assert bridge.endpoint is None
        assert not bridge.is_alive()
        assert children[0].poll() is not None
    finally:
        for child in children:
            if child.poll() is None:
                child.kill()
            child.wait(timeout=2)
            child.stdout.close()


@pytest.mark.parametrize("mode", ["headers", "stall", "drip"])
def test_unary_timeout_bounds_partial_reads(transport, bridge_server, mode):
    client = transport.ConnectJsonTransport(bridge_server(mode), "test")
    started = time.monotonic()
    with pytest.raises(transport.CursorBridgeError, match="timed out|deadline exceeded"):
        client.unary("Agent", "Create", {}, timeout=0.2)
    assert time.monotonic() - started < 0.8


def test_unary_success_and_connect_error(transport, bridge_server):
    client = transport.ConnectJsonTransport(bridge_server("unary"), "test")
    assert client.unary("Agent", "Create", {}, timeout=2) == {"message": "ok"}
    client = transport.ConnectJsonTransport(bridge_server("error"), "test")
    with pytest.raises(transport.CursorBridgeError, match="HTTP 400 connect error"):
        client.unary("Agent", "Create", {}, timeout=2)
    with pytest.raises(transport.CursorBridgeError, match="HTTP 400 connect error"):
        list(client.server_stream("Agent", "Run", {}, deadline=time.monotonic() + 2))


@pytest.mark.parametrize("existing", [False, True])
@pytest.mark.parametrize("failure", [None, "extract", "interrupt", "manifest", "protocol",
                                     "launcher", "publish", "backup"])
def test_download_publishes_only_valid_complete_tree(
    transport, monkeypatch, tmp_path, existing, failure, nested=False,
):
    import hashlib
    import io
    import tarfile

    dest = tmp_path / "cursor-sdk-bridge"
    if existing:
        (dest / "bin").mkdir(parents=True)
        (dest / "bin" / transport._launcher_name()).write_bytes(b"previous launcher")
        (dest / "manifest.json").write_bytes(b"previous manifest")
    before = {str(p.relative_to(dest)): p.read_bytes() for p in dest.rglob("*") if p.is_file()}
    monkeypatch.setattr(transport, "bridge_install_dir", lambda: dest)
    payload = io.BytesIO()
    files = {"manifest.json": json.dumps({"protocol": "sdk.v1"}).encode(),
             "bin/" + transport._launcher_name(): b"new launcher", "support.dat": b"support"}
    if failure == "manifest":
        files.pop("manifest.json")
    if failure == "protocol":
        files["manifest.json"] = b"[]"
    if failure == "launcher":
        files.pop("bin/" + transport._launcher_name())
    with tarfile.open(fileobj=payload, mode="w:gz") as tar:
        for name, content in files.items():
            info = tarfile.TarInfo(("cursor-sdk-bridge/" if nested else "") + name)
            info.size = len(content)
            tar.addfile(info, io.BytesIO(content))
    data = payload.getvalue()
    monkeypatch.setattr(transport, "_fetch_url", lambda _: data)
    monkeypatch.setattr(transport, "_expected_archive_sha256",
                        lambda *_: hashlib.sha256(data).hexdigest())
    original_extract = tarfile.TarFile.extractall

    def extract(archive, path, **kwargs):
        original_extract(archive, path, **kwargs)
        assert {str(p.relative_to(dest)): p.read_bytes()
                for p in dest.rglob("*") if p.is_file()} == before
        if failure == "extract":
            raise OSError("injected extraction failure")
        if failure == "interrupt":
            raise KeyboardInterrupt("injected interruption")

    monkeypatch.setattr(tarfile.TarFile, "extractall", extract)
    original_rename = Path.rename

    def rename(path, target):
        if failure == "publish" and path.name == "extracted":
            raise OSError("injected publication failure")
        if failure == "backup" and path == dest:
            raise OSError("injected backup failure")
        return original_rename(path, target)

    monkeypatch.setattr(Path, "rename", rename)
    if failure is not None and (failure != "backup" or existing):
        with pytest.raises((transport.CursorBridgeError, OSError, KeyboardInterrupt)):
            transport.download_bridge(progress=False)
        assert {str(p.relative_to(dest)): p.read_bytes()
                for p in dest.rglob("*") if p.is_file()} == before
        assert dest.exists() is existing
    else:
        launcher = Path(transport.download_bridge(progress=False))
        assert launcher.read_bytes() == b"new launcher"
        root = dest / "cursor-sdk-bridge" if nested else dest
        assert (root / "support.dat").read_bytes() == b"support"
        assert json.loads((root / "manifest.json").read_text()) == {"protocol": "sdk.v1"}
    assert not list(tmp_path.glob(".cursor-bridge-*"))


@pytest.mark.parametrize("existing", [False, True])
def test_download_nested_archive(transport, monkeypatch, tmp_path, existing):
    test_download_publishes_only_valid_complete_tree(
        transport, monkeypatch, tmp_path, existing, failure=None, nested=True,
    )
