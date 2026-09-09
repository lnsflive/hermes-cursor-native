"""Behavioral capability probes for Hermes Cursor Native."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from contextlib import nullcontext
from dataclasses import dataclass, field
from pathlib import Path

from .discovery import Runtime


def _package_data_root() -> Path:
    from .manifest import package_data_root

    return package_data_root()


def _deploy_plugin(package_root: Path, hermes_home: Path) -> Path:
    source = package_root / "plugin" / "model-providers" / "cursor"
    destination = hermes_home / "plugins" / "model-providers" / "cursor"
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(source, destination)
    return destination


_INTERFACE_PROBE = """
import json
import sys

report = {
    "plugin_seam": False,
    "provider_client_seam": False,
    "errors": [],
}

try:
    from providers.base import ProviderProfile

    method = getattr(ProviderProfile, "create_client", None)
    report["plugin_seam"] = callable(method)
except Exception as exc:
    report["errors"].append(f"plugin_seam: {exc}")

try:
    from agent.agent_runtime_helpers import _provider_supplied_client
    from providers.base import ProviderProfile
    from types import SimpleNamespace
    import providers as providers_mod

    class _ProbeClient:
        HERMES_SKIP_TRANSPORT_WRAP = True
        HERMES_SKIP_ASYNC_WRAP = True

    class _ProbeProfile(ProviderProfile):
        def create_client(self, **kwargs):
            return _ProbeClient()

    providers_mod.register_provider(
        _ProbeProfile(
            name="cursor-probe",
            aliases=("cursor-probe",),
            base_url="sdkbridge://cursor-probe",
        )
    )
    agent = SimpleNamespace(provider="cursor-probe", _client_log_context=lambda: "")
    client = _provider_supplied_client(agent, {"api_key": "probe"})
    report["provider_client_seam"] = client is not None
except Exception as exc:
    report["errors"].append(f"provider_client_seam: {exc}")

print(json.dumps(report))
"""

_PLUGIN_PROBE = """
import json
import os
import sys
from pathlib import Path

home = Path(os.environ["HERMES_HOME"])
report = {
    "plugin_registered": False,
    "create_client": False,
    "skip_flags": False,
    "errors": [],
}

try:
    import providers as providers_mod

    providers_mod._discover_providers()
    profile = providers_mod.get_provider_profile("cursor")
    report["plugin_registered"] = profile is not None
    if profile is None:
        raise RuntimeError("cursor provider not registered")

    client = profile.create_client(api_key="probe", base_url=profile.base_url)
    report["create_client"] = client is not None
    report["skip_flags"] = bool(
        getattr(client, "HERMES_SKIP_TRANSPORT_WRAP", False)
        and getattr(client, "HERMES_SKIP_ASYNC_WRAP", False)
    )
except Exception as exc:
    report["errors"].append(str(exc))

print(json.dumps(report))
"""


@dataclass(frozen=True)
class CapabilityReport:
    """Outcome of probing one Hermes estate."""

    runtime_id: str
    hermes_version: str
    source_root: Path | None
    plugin_seam: bool
    provider_client_seam: bool
    plugin_registered: bool
    client_contract: bool
    notes: tuple[str, ...] = field(default_factory=tuple)

    @property
    def interface_ready(self) -> bool:
        return self.plugin_seam and self.provider_client_seam

    @property
    def plugin_ready(self) -> bool:
        return self.interface_ready and self.plugin_registered and self.client_contract

    def blockers(self) -> list[str]:
        items: list[str] = []
        if not self.plugin_seam:
            items.append("ProviderProfile.create_client is not available")
        if not self.provider_client_seam:
            items.append("Hermes does not route provider-supplied clients")
        if self.interface_ready and not self.plugin_registered:
            items.append("cursor model-provider plugin is not registered")
        if self.plugin_registered and not self.client_contract:
            items.append("cursor plugin client failed contract checks")
        return items


def resolve_hermes_python(runtime: Runtime) -> Path | None:
    """Locate the Hermes venv python for a runtime, including wrapper launchers."""

    names = ("python.exe", "python") if runtime.platform == "windows" else ("python", "python.exe")
    candidates: list[Path] = []
    if runtime.executable is not None:
        directory = Path(runtime.executable).resolve().parent
        candidates.extend(directory / name for name in names)
    if runtime.source_root is not None:
        for venv in ("venv", ".venv"):
            for directory in ("Scripts", "bin"):
                candidates.extend(
                    Path(runtime.source_root) / venv / directory / name for name in names
                )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def _hermes_python(runtime: Runtime) -> Path | None:
    return resolve_hermes_python(runtime)


def _hermes_source(runtime: Runtime) -> Path | None:
    if runtime.source_root is not None and Path(runtime.source_root).is_dir():
        return Path(runtime.source_root)
    if runtime.executable is None:
        return None
    exe = Path(runtime.executable).resolve()
    for parent in exe.parents:
        if (parent / "providers" / "base.py").is_file():
            return parent
    return None


def _run_probe(python: Path, source_root: Path, script: str, *, env: dict[str, str]) -> dict:
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
        detail = (
            completed.stderr.strip() or completed.stdout.strip() or f"exit {completed.returncode}"
        )
        raise RuntimeError(detail)
    return json.loads(completed.stdout.strip() or "{}")


def _probe_version(runtime: Runtime) -> str:
    version = runtime.version
    if runtime.executable is None:
        return version
    try:
        completed = subprocess.run(
            [str(runtime.executable), "--version"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
            check=False,
        )
        if completed.returncode == 0:
            for line in f"{completed.stdout}\n{completed.stderr}".splitlines():
                if "Hermes Agent v" in line:
                    return line.split("Hermes Agent v", 1)[1].split()[0]
    except (OSError, subprocess.TimeoutExpired):
        pass
    return version


def probe_runtime(
    runtime: Runtime,
    *,
    package_root: Path | None = None,
    hermes_home: Path | None = None,
    deployed: bool = False,
) -> CapabilityReport:
    """Probe interfaces by importing Hermes modules and exercising the plugin seam."""
    source_root = _hermes_source(runtime)
    python = _hermes_python(runtime)
    notes: list[str] = []
    plugin_seam = False
    provider_client_seam = False
    plugin_registered = False
    client_contract = False

    if source_root is None or python is None:
        notes.append("could not locate Hermes source checkout or python interpreter")
        return CapabilityReport(
            runtime_id=runtime.runtime_id,
            hermes_version=_probe_version(runtime),
            source_root=source_root,
            plugin_seam=False,
            provider_client_seam=False,
            plugin_registered=False,
            client_contract=False,
            notes=tuple(notes),
        )

    env = os.environ.copy()
    home = hermes_home or Path(runtime.home)
    env["HERMES_HOME"] = str(home)
    env["PYTHONPATH"] = str(source_root)

    try:
        interface = _run_probe(python, source_root, _INTERFACE_PROBE, env=env)
        plugin_seam = bool(interface.get("plugin_seam"))
        provider_client_seam = bool(interface.get("provider_client_seam"))
        for error in interface.get("errors", []):
            notes.append(str(error))
    except (OSError, RuntimeError, json.JSONDecodeError, subprocess.TimeoutExpired) as exc:
        notes.append(f"interface probe failed: {exc}")

    if interface_ready := (plugin_seam and provider_client_seam):
        root = package_root or _package_data_root()
        context = nullcontext(home) if deployed else tempfile.TemporaryDirectory(
            prefix="hermes-cursor-probe-",
        )
        with context as tmp:
            probe_home = Path(tmp)
            if not deployed:
                _deploy_plugin(root, probe_home)
            probe_env = dict(env)
            probe_env["HERMES_HOME"] = str(probe_home)
            try:
                plugin = _run_probe(python, source_root, _PLUGIN_PROBE, env=probe_env)
                plugin_registered = bool(plugin.get("plugin_registered"))
                client_contract = bool(plugin.get("create_client") and plugin.get("skip_flags"))
                for error in plugin.get("errors", []):
                    notes.append(str(error))
            except (OSError, RuntimeError, json.JSONDecodeError, subprocess.TimeoutExpired) as exc:
                notes.append(f"plugin probe failed: {exc}")
    else:
        notes.append("skipped plugin registration probe because core seams are missing")

    return CapabilityReport(
        runtime_id=runtime.runtime_id,
        hermes_version=_probe_version(runtime),
        source_root=source_root,
        plugin_seam=plugin_seam,
        provider_client_seam=provider_client_seam,
        plugin_registered=plugin_registered if interface_ready else False,
        client_contract=client_contract if interface_ready else False,
        notes=tuple(notes),
    )
