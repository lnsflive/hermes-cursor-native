"""Post-install verification helpers and receipt generation."""

from __future__ import annotations

import json
import os
import re
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path

from .capabilities import resolve_hermes_python
from .discovery import Runtime

_AUTH_LINE = re.compile(r"^(cursor|Cursor)\s*:\s*(logged in|logged out)\b", re.IGNORECASE)


@dataclass(frozen=True)
class InstallReceipt:
    host: str
    runtime_id: str
    hermes_version: str
    hermes_home: str
    plugin_path: str
    plugin_installed: bool
    bridge_path: str
    bridge_installed: bool
    auth_status: str
    auth_source: str
    model_catalog_count: int | None
    model_catalog_error: str
    contract_checks: dict[str, bool]
    chat_probe: str
    notes: tuple[str, ...]

    def to_dict(self) -> dict:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)


def _hostname() -> str:
    try:
        import socket

        return socket.gethostname()
    except OSError:
        return "unknown"


def _safe_auth_status(
    hermes: Path, profile_args: list[str], cwd: Path, hermes_home: Path,
) -> tuple[str, str]:
    try:
        completed = subprocess.run(
            [str(hermes), *profile_args, "auth", "status", "cursor"],
            cwd=cwd,
            env={**os.environ, "HERMES_HOME": str(hermes_home)},
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
            check=False,
        )
    except OSError:
        return "unknown", "auth_status_probe_failed"
    except subprocess.TimeoutExpired:
        return "unknown", "auth_status_probe_timed_out"
    text = f"{completed.stdout}\n{completed.stderr}"
    for line in text.splitlines():
        match = _AUTH_LINE.match(line.strip())
        if match:
            return match.group(2).lower(), ""
    if completed.returncode != 0:
        return "unknown", "auth_status_command_failed"
    return "unknown", "auth_status_unparsed"


def _model_catalog_count(
    python: Path,
    source_root: Path,
    hermes_home: Path,
    *,
    logged_in: bool,
) -> tuple[int | None, str]:
    if not logged_in:
        return None, ""
    script = """
import json
import os

os.environ.setdefault("HERMES_HOME", os.environ["HERMES_HOME"])
try:
    import providers as providers_mod
    providers_mod._discover_providers()
    from hermes_cli.auth import resolve_api_key_provider_credentials

    creds = resolve_api_key_provider_credentials("cursor")
    source = str(creds.get("source") or "")
    if not creds.get("api_key"):
        print(json.dumps({"count": None, "source": source, "error": "no_credentials"}))
        raise SystemExit(0)
    profile = providers_mod.get_provider_profile("cursor")
    models = profile.fetch_models() if profile else None
    print(json.dumps({"count": len(models or []), "source": source}))
except Exception as exc:
    print(json.dumps({"count": None, "error": type(exc).__name__}))
"""
    env = os.environ.copy()
    env["HERMES_HOME"] = str(hermes_home)
    env["PYTHONPATH"] = str(source_root)
    completed = subprocess.run(
        [str(python), "-c", script],
        cwd=source_root,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
        check=False,
    )
    if completed.returncode != 0:
        return None, "catalog_probe_failed"
    try:
        payload = json.loads(completed.stdout.strip() or "{}")
        count = payload.get("count")
        error = str(payload.get("error") or "")
        return (int(count) if isinstance(count, int) else None), error
    except (json.JSONDecodeError, TypeError, ValueError):
        return None, "catalog_probe_invalid_json"


def _runtime_auth_probe(
    python: Path,
    source_root: Path,
    hermes_home: Path,
    *,
    logged_in: bool,
) -> str:
    """Exercise stock Hermes runtime credential resolution for cursor."""
    if not logged_in:
        return "skipped_logged_out"
    script = """
import json
import os

os.environ.setdefault("HERMES_HOME", os.environ["HERMES_HOME"])
try:
    import providers as providers_mod
    providers_mod._discover_providers()
    from hermes_cli.runtime_provider import resolve_runtime_provider

    runtime = resolve_runtime_provider(requested="cursor")
    ok = bool(runtime and runtime.get("api_key"))
    source = str(runtime.get("source") or "") if isinstance(runtime, dict) else ""
    print(json.dumps({"ok": ok, "source": source}))
except Exception as exc:
    print(json.dumps({"ok": False, "error": type(exc).__name__}))
"""
    env = os.environ.copy()
    env["HERMES_HOME"] = str(hermes_home)
    env["PYTHONPATH"] = str(source_root)
    completed = subprocess.run(
        [str(python), "-c", script],
        cwd=source_root,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
        check=False,
    )
    if completed.returncode != 0:
        return "runtime_probe_failed"
    try:
        payload = json.loads(completed.stdout.strip() or "{}")
        if payload.get("ok"):
            return "runtime_credentials_ok"
        if payload.get("error"):
            return f"runtime_error:{payload['error']}"
        return "runtime_missing_credentials"
    except json.JSONDecodeError:
        return "runtime_probe_invalid_json"


def run_contract_checks(
    python: Path,
    source_root: Path,
    hermes_home: Path,
) -> dict[str, bool]:
    from .capabilities import probe_runtime

    hermes_exe = python.parent / "hermes"
    runtime = Runtime(
        "verify",
        ("cli",),
        "linux",
        hermes_home,
        source_root,
        hermes_exe if hermes_exe.is_file() else None,
        "",
        True,
        "verify",
    )
    report = probe_runtime(runtime, hermes_home=hermes_home, deployed=True)
    return {
        "plugin_seam": report.plugin_seam,
        "provider_client_seam": report.provider_client_seam,
        "plugin_registered": report.plugin_registered,
        "client_contract": report.client_contract,
    }


def resolve_status_bridge(runtime: Runtime, profile: str) -> tuple[Path | None, tuple[str, ...]]:
    """Use the selected runtime's installed provider resolver without starting a bridge."""
    home = Path(runtime.home)
    selected_home = home if profile == "default" else home / "profiles" / profile
    python = resolve_hermes_python(runtime)
    source = Path(runtime.source_root) if runtime.source_root else None
    note = "bridge resolver unavailable: selected Hermes Python missing"
    if python is not None and source is not None and source.is_dir():
        script = """
import importlib
import json
import shutil
from pathlib import Path
import providers
providers._discover_providers()
profile = providers.get_provider_profile("cursor")
if profile is None:
    raise RuntimeError("Cursor provider not registered")
package = profile.__class__.__module__
client = importlib.import_module(package + ".cursor_bridge_client")
transport = importlib.import_module(package + ".cursor_bridge_transport")
command = transport.resolve_bridge_command(client.load_bridge_settings()["command"])
path = Path(shutil.which(command) or command).resolve() if command else None
print(json.dumps({"bridge": str(path) if path and path.is_file() else None}))
"""
        try:
            result = subprocess.run(
                [str(python), "-c", script], cwd=source,
                env={**os.environ, "HERMES_HOME": str(selected_home), "PYTHONPATH": str(source)},
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                timeout=30, check=False,
            )
            if result.returncode == 0:
                payload = json.loads(result.stdout.strip())
                bridge = payload["bridge"]
                if bridge:
                    return Path(bridge), ()
                return None, ("bridge resolver found no launcher",)
            note = "bridge resolver unavailable: provider probe failed"
        except (OSError, subprocess.TimeoutExpired, ValueError, KeyError, TypeError):
            note = "bridge resolver unavailable: provider probe failed"
    # A partial runtime can still report managed files, but cannot resolve
    # wheel/config/PATH precedence. Keep that limitation visible in the receipt.
    bridge_root = selected_home / "cursor-sdk-bridge"
    if profile != "default" and not bridge_root.exists():
        bridge_root = home / "cursor-sdk-bridge"
    expected = "cursor-sdk-bridge.exe" if runtime.platform == "windows" else "cursor-sdk-bridge"
    matches = [path for path in bridge_root.rglob(expected) if path.is_file()]
    if len(matches) == 1:
        return matches[0], (note,)
    return None, (note, f"bridge: expected one launcher, found {len(matches)}")


def collect_receipt(
    runtime: Runtime,
    *,
    bridge_path: Path | None,
    notes: tuple[str, ...] = (),
    profile: str = "default",
) -> InstallReceipt:
    hermes_home = Path(runtime.home)
    probe_home = hermes_home if profile == "default" else hermes_home / "profiles" / profile
    legacy_plugin = probe_home / "plugins" / "model-providers" / "cursor"
    native_plugin = probe_home / "plugins" / "cursor"
    plugin_path = native_plugin if native_plugin.is_dir() else legacy_plugin
    hermes = Path(runtime.executable)  # type: ignore[arg-type]
    source_root = Path(runtime.source_root) if runtime.source_root else Path(".")
    profile_args = ["-p", profile]
    auth_status, auth_note = _safe_auth_status(hermes, profile_args, source_root, hermes_home)
    logged_in = auth_status == "logged in"
    python = resolve_hermes_python(runtime)
    contract = (
        run_contract_checks(python, source_root, probe_home)
        if python is not None and python.is_file() and source_root.is_dir()
        else {
            "plugin_seam": False,
            "provider_client_seam": False,
            "plugin_registered": plugin_path.is_dir(),
            "client_contract": False,
        }
    )
    catalog_count, catalog_error = (
        _model_catalog_count(python, source_root, probe_home, logged_in=logged_in)
        if python is not None and python.is_file() and source_root.is_dir()
        else (None, "python_missing")
    )
    runtime_probe = (
        _runtime_auth_probe(python, source_root, probe_home, logged_in=logged_in)
        if python is not None and python.is_file() and source_root.is_dir()
        else "runtime_probe_unavailable"
    )
    auth_source = ""
    if logged_in and runtime_probe == "runtime_credentials_ok":
        auth_source = "runtime_resolved"
    merged_notes = tuple(notes)
    if auth_note:
        merged_notes = (*merged_notes, f"auth: {auth_note}")
    return InstallReceipt(
        host=_hostname(),
        runtime_id=runtime.runtime_id,
        hermes_version=runtime.version,
        hermes_home=str(hermes_home),
        plugin_path=str(plugin_path),
        plugin_installed=plugin_path.is_dir(),
        bridge_path=str(bridge_path) if bridge_path is not None else "",
        bridge_installed=bridge_path is not None and bridge_path.is_file(),
        auth_status=auth_status,
        auth_source=auth_source,
        model_catalog_count=catalog_count,
        model_catalog_error=catalog_error,
        contract_checks=contract,
        chat_probe=runtime_probe,
        notes=merged_notes,
    )
