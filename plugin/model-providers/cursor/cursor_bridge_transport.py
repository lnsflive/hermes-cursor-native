"""Cursor SDK bridge process management + Connect JSON transport.

Implements the `sdk.v1` bridge protocol from https://github.com/cursor/sdk-bridge:

* locate or install the ``cursor-sdk-bridge`` launcher,
* spawn it with ``CURSOR_API_KEY`` and parse the ``cursor-sdk-bridge ready``
  stderr discovery line,
* speak Connect over HTTP/1.1 with JSON encoding — unary RPCs are plain JSON
  POSTs, server streams use enveloped ``application/connect+json`` frames
  (1 flags byte + 4-byte big-endian length + payload).

The bridge is HTTP/1.1 only; classic gRPC clients do not work.  JSON encoding
is used so Hermes does not need generated protobuf stubs (proto3 has a
canonical JSON mapping and Connect servers accept it natively).
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import shutil
import struct
import subprocess
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from hermes_constants import get_hermes_home

logger = logging.getLogger(__name__)

READY_LINE_PREFIX = "cursor-sdk-bridge ready "
_STARTUP_TIMEOUT_SECONDS = 45.0
_SHUTDOWN_TIMEOUT_SECONDS = 5.0

# Default bridge version installed by `hermes model` when no bridge is found.
# Matches a released @cursor/sdk / cursor-sdk version that includes the
# custom-tools callback surface (landed in SDK 1.0.2x, Aug 2026).  Users can
# override via config.yaml `cursor_bridge.download_version`.
DEFAULT_BRIDGE_VERSION = "1.0.27"
# Primary distribution: GitHub release assets verified against digests pinned
# in this Hermes build. Unknown version/artifact pairs fail closed.
_GITHUB_RELEASE_URL_TEMPLATE = (
    "https://github.com/cursor/sdk-bridge/releases/download/v{version}/"
    "cursor-sdk-bridge-standalone-{os}-{arch}.tar.gz"
)
_PINNED_BRIDGE_SHA256 = {
    "1.0.27": {
        "cursor-sdk-bridge-standalone-darwin-arm64.tar.gz": (
            "0d544fd30d5c0f93cb8ade0cb5fbfbea10cf2e55c4669f74f26dd36d6a5bb0ba"
        ),
        "cursor-sdk-bridge-standalone-darwin-x64.tar.gz": (
            "f8d6be39cc379420746cc7d09adad51843d095802a9af872858ad5fb3304b1f6"
        ),
        "cursor-sdk-bridge-standalone-linux-arm64.tar.gz": (
            "6d2e7b12875003045923d038a56df06b309e80a7d2500a4c5261d5511b1db40c"
        ),
        "cursor-sdk-bridge-standalone-linux-x64.tar.gz": (
            "114e6b7b284c31006979e8b4340c66ba60015d2143f62d76ce4d7584f80068c2"
        ),
        "cursor-sdk-bridge-standalone-win32-x64.tar.gz": (
            "c373c01da4a8808137cf8578adc6d7f5a4a8a9f0bf5dd288fbba9b6b3e62d9b3"
        ),
    }
}


class CursorBridgeError(RuntimeError):
    """Raised for bridge process, transport, or Connect-level failures."""

    def __init__(self, message: str, *, code: str | None = None):
        super().__init__(message)
        self.code = code


@dataclass
class BridgeEndpoint:
    """Where a running bridge listens and how to authenticate to it."""

    url: str
    auth_token: str
    server_version: str = ""
    pid: int | None = None
    workspace_ref: str = ""
    state_root: str = ""


def parse_ready_line(line: str) -> dict[str, Any] | None:
    """Parse one stderr line; return the discovery payload or None.

    Never log the returned payload verbatim — older bridges inline the auth
    token in the discovery JSON.
    """
    if not line.startswith(READY_LINE_PREFIX):
        return None
    raw = line[len(READY_LINE_PREFIX) :].strip()
    try:
        payload = json.loads(raw)
    except ValueError as exc:
        raise CursorBridgeError(f"invalid bridge discovery JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise CursorBridgeError("bridge discovery payload is not a JSON object")
    return payload


def validate_discovery(payload: dict[str, Any]) -> None:
    if payload.get("schemaVersion") != 1:
        raise CursorBridgeError(
            f"unsupported bridge discovery schemaVersion={payload.get('schemaVersion')!r}"
        )
    if payload.get("transport") != "tcp":
        raise CursorBridgeError(f"unsupported bridge transport={payload.get('transport')!r}")
    if payload.get("protocol") != "connect":
        raise CursorBridgeError(f"unsupported bridge protocol={payload.get('protocol')!r}")


def endpoint_from_discovery(payload: dict[str, Any]) -> BridgeEndpoint:
    validate_discovery(payload)
    url = str(payload.get("url") or "").strip()
    if not url:
        host = str(payload.get("host") or "").strip()
        port = payload.get("port")
        if not host or not isinstance(port, int):
            raise CursorBridgeError("bridge discovery has no url/host/port")
        if ":" in host and not host.startswith("["):
            host = f"[{host}]"
        url = f"http://{host}:{port}"

    token = str(payload.get("authToken") or "").strip()
    if not token:
        token_file = str(payload.get("authTokenFile") or "").strip()
        if not token_file:
            raise CursorBridgeError("bridge discovery has no authTokenFile")
        try:
            token = Path(token_file).read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise CursorBridgeError(f"could not read bridge auth token file: {exc}") from exc
    if not token:
        raise CursorBridgeError("bridge auth token is empty")

    return BridgeEndpoint(
        url=url,
        auth_token=token,
        server_version=str(payload.get("serverVersion") or ""),
        pid=payload.get("pid") if isinstance(payload.get("pid"), int) else None,
        workspace_ref=str(payload.get("workspaceRef") or ""),
        state_root=str(payload.get("stateRoot") or ""),
    )


# ── Bridge binary resolution ──────────────────────────────────────────────


def bridge_install_dir() -> Path:
    """Hermes-managed bridge install location (profile-aware)."""
    return get_hermes_home() / "cursor-sdk-bridge"


def _launcher_name() -> str:
    # Official win32 release assets ship a native .exe, while POSIX archives
    # ship an extensionless launcher.
    return "cursor-sdk-bridge.exe" if os.name == "nt" else "cursor-sdk-bridge"


def _bridge_from_cursor_sdk_wheel() -> str | None:
    """Locate the bridge bundled inside an installed ``cursor-sdk`` wheel."""
    try:
        import importlib.util

        spec = importlib.util.find_spec("cursor_sdk")
    except (ImportError, ValueError):
        return None
    if spec is None or not spec.submodule_search_locations:
        return None
    for root in spec.submodule_search_locations:
        base = Path(root)
        for candidate in (
            base / "cursor-sdk-bridge" / "bin" / _launcher_name(),
            base / "_bridge" / "bin" / _launcher_name(),
            base / "bridge" / "bin" / _launcher_name(),
        ):
            if candidate.exists():
                return str(candidate)
        # Fall back to a shallow scan — wheel layout is not contractual.
        try:
            for candidate in base.glob(f"**/bin/{_launcher_name()}"):
                return str(candidate)
        except OSError:
            continue
    return None


def resolve_bridge_command(configured_command: str = "") -> str | None:
    """Resolve the bridge launcher path, or None when not installed.

    Resolution order:
      1. ``cursor_bridge.command`` from config.yaml (caller passes it in)
      2. the bridge embedded in an installed ``cursor-sdk`` PyPI wheel
      3. ``CURSOR_SDK_BRIDGE_BIN`` (the upstream adapter convention)
      4. ``cursor-sdk-bridge`` on PATH
      5. the Hermes-managed install under ``$HERMES_HOME/cursor-sdk-bridge/``
    """
    configured = (configured_command or "").strip()
    if configured:
        expanded = os.path.expanduser(configured)
        if shutil.which(expanded) or Path(expanded).exists():
            return expanded
        logger.warning("Configured cursor_bridge.command %r not found", configured)

    wheel_bridge = _bridge_from_cursor_sdk_wheel()
    if wheel_bridge:
        return wheel_bridge

    env_bin = os.getenv("CURSOR_SDK_BRIDGE_BIN", "").strip()
    if env_bin and Path(os.path.expanduser(env_bin)).exists():
        return os.path.expanduser(env_bin)

    on_path = shutil.which("cursor-sdk-bridge")
    if on_path:
        return on_path

    for managed in (
        bridge_install_dir() / "bin" / _launcher_name(),
        bridge_install_dir() / "cursor-sdk-bridge" / "bin" / _launcher_name(),
    ):
        if managed.exists():
            return str(managed)
    return None


def bridge_platform() -> tuple[str, str]:
    """Return the verified (os, arch) pair used by the bridge download URL."""
    import platform as _platform
    import sys

    if sys.platform == "win32":
        os_name = "win32"
    elif sys.platform == "darwin":
        os_name = "darwin"
    elif sys.platform.startswith("linux"):
        os_name = "linux"
    else:
        raise CursorBridgeError(f"unsupported bridge operating system: {sys.platform}")

    machine = _platform.machine().lower()
    if machine in {"x86_64", "amd64", "x64"}:
        arch = "x64"
    elif machine in {"arm64", "aarch64"}:
        arch = "arm64"
    else:
        raise CursorBridgeError(f"unsupported bridge architecture: {machine or 'unknown'}")
    if os_name == "win32" and arch != "x64":
        raise CursorBridgeError("unsupported bridge architecture: Windows ARM64")
    return os_name, arch


def _fetch_url(url: str, timeout: float = 120) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "hermes-cli"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def _expected_archive_sha256(version: str, archive_name: str) -> str | None:
    """Return the digest pinned in this Hermes build; never trust remote metadata."""
    return _PINNED_BRIDGE_SHA256.get(version, {}).get(archive_name)


def download_bridge(version: str = "", *, progress: bool = True) -> str:
    """Download and unpack the bridge archive into the Hermes-managed dir.

    Downloads the GitHub release asset only when this Hermes build contains a
    pinned digest for it. Returns the launcher path. Called from setup flows
    (`hermes model`) — the runtime client never downloads implicitly.
    """
    import hashlib
    import tarfile
    import tempfile

    version = (version or DEFAULT_BRIDGE_VERSION).strip().lstrip("v")
    os_name, arch = bridge_platform()
    archive_name = f"cursor-sdk-bridge-standalone-{os_name}-{arch}.tar.gz"
    dest_root = bridge_install_dir()

    if progress:
        print(f"  Downloading Cursor SDK bridge {version} ({os_name}/{arch})...")

    expected = _expected_archive_sha256(version, archive_name)
    if not expected:
        raise CursorBridgeError(
            f"bridge checksum metadata unavailable for {archive_name}; refusing download"
        )

    github_url = _GITHUB_RELEASE_URL_TEMPLATE.format(version=version, os=os_name, arch=arch)
    try:
        data = _fetch_url(github_url)
        actual = hashlib.sha256(data).hexdigest()
        if actual != expected:
            raise CursorBridgeError(
                f"bridge archive checksum mismatch: expected {expected}, got {actual}"
            )
        if progress:
            print("  ✓ SHA256 verified against the digest pinned in Hermes")
    except CursorBridgeError:
        raise
    except (urllib.error.URLError, OSError) as exc:
        raise CursorBridgeError(f"bridge download failed: {github_url}: {exc}") from exc

    # Keep incomplete archives out of the managed path, including on interruption.
    dest_root.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".cursor-bridge-stage-", dir=dest_root.parent) as tmp:
        staging = Path(tmp)
        archive_path = staging / "bridge.tar.gz"
        archive_path.write_bytes(data)
        extracted = staging / "extracted"
        extracted.mkdir()
        try:
            with tarfile.open(archive_path, "r:gz") as tar:
                tar.extractall(extracted, filter="data")
        except (tarfile.TarError, OSError) as exc:
            raise CursorBridgeError(f"bridge archive extraction failed: {exc}") from exc

        # Standalone releases are flat; packaged mirrors have a nested root.
        bridge_root = None
        for candidate in (extracted, extracted / "cursor-sdk-bridge"):
            if (candidate / "manifest.json").is_file():
                bridge_root = candidate
                break
        if bridge_root is None:
            raise CursorBridgeError("bridge manifest not found in downloaded archive")
        try:
            manifest = json.loads((bridge_root / "manifest.json").read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise CursorBridgeError(f"bridge manifest unreadable: {exc}") from exc
        if not isinstance(manifest, dict) or manifest.get("protocol") != "sdk.v1":
            raise CursorBridgeError("bridge manifest must declare protocol 'sdk.v1'")

        launcher = bridge_root / "bin" / _launcher_name()
        if not launcher.is_file():
            raise CursorBridgeError(f"bridge launcher missing in archive: {launcher}")
        if os.name != "nt":
            launcher.chmod(launcher.stat().st_mode | 0o755)
        relative_launcher = launcher.relative_to(extracted)

        backup_dir = None
        backup = None
        try:
            if dest_root.exists() or dest_root.is_symlink():
                backup_dir = Path(tempfile.mkdtemp(
                    prefix=".cursor-bridge-backup-", dir=dest_root.parent,
                ))
                backup = backup_dir / "previous"
                dest_root.rename(backup)
            extracted.rename(dest_root)
        except BaseException:
            if backup is not None and (backup.exists() or backup.is_symlink()):
                # Retain the backup if restoration itself fails, for recovery.
                backup.rename(dest_root)
            if backup_dir is not None:
                shutil.rmtree(backup_dir)
            raise
        else:
            if backup_dir is not None:
                shutil.rmtree(backup_dir)

    launcher = dest_root / relative_launcher
    if progress:
        print(f"  ✓ Installed Cursor SDK bridge → {launcher}")
    return str(launcher)


# ── Bridge process ────────────────────────────────────────────────────────


def _build_subprocess_env(api_key: str) -> dict[str, str]:
    # The bridge is a model-driving executor: it needs the Cursor credential
    # but must not inherit Tier-1 Hermes secrets (gateway bot tokens, etc.).
    from tools.environments.local import hermes_subprocess_env

    env = hermes_subprocess_env(inherit_credentials=False)
    credential_markers = ("KEY", "TOKEN", "SECRET", "PASSWORD", "CREDENTIAL", "AUTH")
    for name in list(env):
        if any(marker in name.upper() for marker in credential_markers):
            env.pop(name, None)
    env["CURSOR_API_KEY"] = api_key
    env["CURSOR_SDK_CLIENT_LANGUAGE"] = "python"
    return env


class CursorBridgeProcess:
    """Owns one ``cursor-sdk-bridge`` child process."""

    def __init__(
        self,
        *,
        command: str,
        api_key: str,
        workspace: str,
        tool_callback_url: str = "",
        tool_callback_auth_token: str = "",
    ):
        self._command = command
        self._api_key = api_key
        self._workspace = str(Path(workspace).resolve())
        self._tool_callback_url = tool_callback_url
        self._tool_callback_auth_token = tool_callback_auth_token
        self._process: subprocess.Popen[str] | None = None
        self.endpoint: BridgeEndpoint | None = None

    @property
    def workspace(self) -> str:
        return self._workspace

    def is_alive(self) -> bool:
        return self._process is not None and self._process.poll() is None

    def start(self, *, deadline: float | None = None) -> BridgeEndpoint:
        _remaining_timeout(_STARTUP_TIMEOUT_SECONDS, deadline, "bridge startup")
        argv = [self._command, "--workspace", self._workspace]
        if self._tool_callback_url:
            argv += ["--tool-callback-url", self._tool_callback_url]
            if self._tool_callback_auth_token:
                argv += ["--tool-callback-auth-token", self._tool_callback_auth_token]
        try:
            from hermes_cli._subprocess_compat import windows_hide_flags

            self._process = subprocess.Popen(
                argv,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                stdin=subprocess.DEVNULL,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=_build_subprocess_env(self._api_key),
                creationflags=windows_hide_flags(),
            )
        except OSError as exc:
            raise CursorBridgeError(
                f"could not launch Cursor SDK bridge {self._command!r}: {exc}"
            ) from exc

        try:
            discovery = self._await_ready_line(self._process, deadline=deadline)
            endpoint = endpoint_from_discovery(discovery)
        except BaseException:
            self.stop(force=True)
            raise
        self.endpoint = endpoint
        logger.info(
            "Cursor SDK bridge ready (pid=%s, version=%s)",
            endpoint.pid,
            endpoint.server_version,
        )
        return endpoint

    def _await_ready_line(
        self, process: subprocess.Popen[str], *, deadline: float | None = None,
    ) -> dict[str, Any]:
        """Scan stderr for the discovery line; keep draining forever after.

        A full stderr pipe blocks the bridge, so the scanner thread never
        stops reading.
        """
        import queue as _queue

        found: _queue.Queue[dict[str, Any] | Exception] = _queue.Queue(maxsize=1)

        def scan() -> None:
            if process.stderr is None:
                found.put(CursorBridgeError("bridge process exposed no stderr pipe"))
                return
            diagnostics: list[str] = []
            for line in process.stderr:
                line = line.rstrip("\n")
                try:
                    payload = parse_ready_line(line)
                except CursorBridgeError as exc:
                    found.put(exc)
                    payload = None
                if payload is None:
                    if len(diagnostics) < 60:
                        diagnostics.append(line)
                    continue
                found.put(payload)
                for _ in process.stderr:  # drain so the bridge never blocks
                    pass
                return
            found.put(
                CursorBridgeError(
                    "Cursor SDK bridge exited before emitting its ready line. "
                    "Stderr tail:\n" + "\n".join(diagnostics[-20:])
                )
            )

        threading.Thread(target=scan, daemon=True, name="cursor-bridge-stderr").start()
        import queue as _queue

        try:
            wait_timeout = _remaining_timeout(_STARTUP_TIMEOUT_SECONDS, deadline, "bridge startup")
            result = found.get(timeout=wait_timeout)
        except _queue.Empty:
            raise CursorBridgeError(
                f"timed out after {wait_timeout:.2f}s waiting for the "
                "Cursor SDK bridge ready line"
            ) from None
        if isinstance(result, Exception):
            raise result
        return result

    def stop(self, *, force: bool = False) -> None:
        process, self._process = self._process, None
        self.endpoint = None
        if process is None:
            return
        if process.poll() is None:
            try:
                if force:
                    process.kill()
                else:
                    process.terminate()
                    process.wait(timeout=_SHUTDOWN_TIMEOUT_SECONDS)
            except subprocess.TimeoutExpired:
                with contextlib.suppress(OSError):
                    process.kill()
            except OSError:
                pass
        with contextlib.suppress(subprocess.TimeoutExpired, OSError):
            process.wait(timeout=1)


# ── Connect JSON transport ────────────────────────────────────────────────


class ConnectJsonTransport:
    """Connect-over-HTTP/1.1 client with JSON message encoding.

    Unary RPCs: ``POST {base}/sdk.v1.<Service>/<Method>`` with
    ``application/json``; errors arrive as non-200 with a Connect error JSON
    body (``{"code": ..., "message": ...}``).

    Server streams: ``application/connect+json`` enveloped frames.  Each frame
    is 1 flags byte + 4-byte big-endian payload length + payload.  A frame
    with flags bit ``0x02`` is the JSON EndStreamResponse (holds ``error``
    when the stream failed).
    """

    def __init__(self, base_url: str, auth_token: str):
        self.base_url = base_url.rstrip("/")
        self._token = auth_token

    def _request(self, path: str, content_type: str, body: bytes) -> urllib.request.Request:
        return urllib.request.Request(
            f"{self.base_url}{path}",
            data=body,
            method="POST",
            headers={
                "Content-Type": content_type,
                "Authorization": f"Bearer {self._token}",
                "Connect-Protocol-Version": "1",
            },
        )

    @staticmethod
    def _raise_connect_error(raw: bytes, http_status: int | None = None) -> None:
        code = None
        message = raw.decode("utf-8", "replace")[:2000]
        try:
            payload = json.loads(raw.decode("utf-8"))
            if isinstance(payload, dict):
                code = payload.get("code")
                message = str(payload.get("message") or message)
        except ValueError:
            pass
        prefix = f"HTTP {http_status} " if http_status else ""
        raise CursorBridgeError(f"{prefix}connect error [{code}]: {message}", code=code)

    def unary(
        self,
        service: str,
        method: str,
        request: dict[str, Any],
        *,
        timeout: float = 60.0,
    ) -> dict[str, Any]:
        deadline = time.monotonic() + timeout
        body = json.dumps(request).encode("utf-8")
        req = self._request(f"/sdk.v1.{service}/{method}", "application/json", body)
        try:
            with urllib.request.urlopen(
                req, timeout=_remaining_timeout(timeout, deadline, f"{service}/{method}")
            ) as reply:
                raw = _read_response(reply, timeout, deadline)
        except urllib.error.HTTPError as err:
            with err:
                self._raise_connect_error(
                    _read_response(err.fp, timeout, deadline), http_status=err.code
                )
        except (urllib.error.URLError, OSError) as err:
            raise CursorBridgeError(f"{service}/{method}: {err}") from None
        if not raw:
            return {}
        try:
            payload = json.loads(raw.decode("utf-8"))
        except ValueError as exc:
            raise CursorBridgeError(f"{service}/{method}: invalid JSON response: {exc}") from exc
        return payload if isinstance(payload, dict) else {}

    def server_stream(
        self,
        service: str,
        method: str,
        request: dict[str, Any],
        *,
        read_timeout: float = 90.0,
        deadline: float | None = None,
    ) -> Iterator[dict[str, Any]]:
        """Yield stream messages as dicts until the EndStreamResponse frame.

        ``read_timeout`` bounds a single socket read; the bridge emits
        keepalives every ~15s so a quiet-but-alive stream never trips it.
        ``deadline`` (monotonic timestamp) bounds the whole stream.
        """
        payload = json.dumps(request).encode("utf-8")
        body = struct.pack(">BI", 0, len(payload)) + payload
        req = self._request(f"/sdk.v1.{service}/{method}", "application/connect+json", body)
        try:
            reply = urllib.request.urlopen(
                req, timeout=_remaining_timeout(read_timeout, deadline, f"{service}/{method}")
            )
        except urllib.error.HTTPError as err:
            with err:
                self._raise_connect_error(
                    _read_response(err.fp, read_timeout, deadline), http_status=err.code
                )
            return  # unreachable; keeps type-checkers happy
        except (urllib.error.URLError, OSError) as err:
            raise CursorBridgeError(f"{service}/{method}: {err}") from None

        with reply:
            while True:
                if deadline is not None and time.monotonic() > deadline:
                    raise CursorBridgeError(f"{service}/{method}: stream deadline exceeded")
                header = _read_exact(
                    reply, 5, what=f"{service}/{method} frame header",
                    read_timeout=read_timeout, deadline=deadline,
                )
                flags, length = struct.unpack(">BI", header)
                frame = _read_exact(
                    reply, length, what=f"{service}/{method} frame body",
                    read_timeout=read_timeout, deadline=deadline,
                )
                if flags & 0x02:
                    end = json.loads(frame) if frame else {}
                    error = end.get("error") if isinstance(end, dict) else None
                    if error:
                        self._raise_connect_error(json.dumps(error).encode("utf-8"))
                    return
                if not frame:
                    continue
                try:
                    message = json.loads(frame.decode("utf-8"))
                except ValueError as exc:
                    raise CursorBridgeError(
                        f"{service}/{method}: invalid JSON stream frame: {exc}"
                    ) from exc
                if isinstance(message, dict):
                    yield message


def _remaining_timeout(read_timeout: float, deadline: float | None, what: str) -> float:
    if deadline is None:
        return read_timeout
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise CursorBridgeError(f"{what}: stream deadline exceeded")
    return min(read_timeout, remaining)


def _read_response(stream: Any, read_timeout: float, deadline: float | None) -> bytes:
    chunks = []
    while True:
        chunk = _read_chunk(stream, 65536, read_timeout, deadline, "response body")
        if not chunk:
            return b"".join(chunks)
        chunks.append(chunk)


def _read_chunk(
    stream: Any, count: int, read_timeout: float, deadline: float | None, what: str,
) -> bytes:
    try:
        timeout = _remaining_timeout(read_timeout, deadline, what)
        # One underlying read at a time lets partial frames share one deadline.
        if stream.fp is not None:
            stream.fp.raw._sock.settimeout(timeout)
        return stream.read1(count)
    except OSError as exc:
        raise CursorBridgeError(f"{what}: stream read failed: {exc}") from None


def _read_exact(
    stream: Any, count: int, *, what: str,
    read_timeout: float = 90.0, deadline: float | None = None,
) -> bytes:
    chunks = b""
    while len(chunks) < count:
        chunk = _read_chunk(stream, count - len(chunks), read_timeout, deadline, what)
        if not chunk:
            raise CursorBridgeError(f"{what}: stream ended before EndStreamResponse")
        chunks += chunk
    return chunks
