"""Local installation preflight helpers."""

from __future__ import annotations

import hashlib
import hmac
import platform
import subprocess
from collections.abc import Callable, Mapping
from pathlib import Path

from .install_plan import GitState

_PROVIDER_FILES = (
    "agent/agent_init.py",
    "agent/agent_runtime_helpers.py",
    "agent/auxiliary_client.py",
    "agent/conversation_loop.py",
    "agent/cursor_bridge_client.py",
    "agent/cursor_bridge_transport.py",
    "agent/cursor_bridge_wire.py",
    "agent/cursor_sdk_auth.py",
    "cli-config.yaml.example",
    "cli.py",
    "gateway/run.py",
    "gateway/slash_commands.py",
    "hermes_cli/auth.py",
    "hermes_cli/cli_commands_mixin.py",
    "hermes_cli/commands.py",
    "hermes_cli/config_defaults.py",
    "hermes_cli/cursor_cloud.py",
    "hermes_cli/main.py",
    "hermes_cli/model_setup_flows.py",
    "hermes_cli/model_switch.py",
    "hermes_cli/models.py",
    "hermes_cli/providers.py",
    "hermes_cli/subcommands/cursor_agent.py",
    "plugins/model-providers/cursor/__init__.py",
    "plugins/model-providers/cursor/plugin.yaml",
)


BlobReader = Callable[[Path, str], bytes]


def _git_head_blob(source_root: Path, relative: str) -> bytes:
    result = subprocess.run(
        ["git", "-C", str(source_root), "show", f"HEAD:{relative}"],
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise OSError(result.stderr.decode("utf-8", "replace").strip())
    return result.stdout


def provider_installation_complete(
    source_root: Path,
    expected_sha256: Mapping[str, str],
    blob_reader: BlobReader = _git_head_blob,
) -> bool:
    if set(expected_sha256) != set(_PROVIDER_FILES):
        return False
    for relative in _PROVIDER_FILES:
        try:
            actual = hashlib.sha256(blob_reader(source_root, relative)).hexdigest()
        except OSError:
            return False
        if not hmac.compare_digest(actual, expected_sha256[relative].lower()):
            return False
    return True


def detect_architecture() -> str:
    machine = platform.machine().casefold()
    if machine in {"arm64", "aarch64"}:
        return "arm64"
    if machine in {"x86_64", "amd64", "x64"}:
        return "x64"
    raise RuntimeError(f"Unsupported architecture: {machine or 'unknown'}")


def probe_git_state(source_root: Path) -> GitState:
    def run(*args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", "-C", str(source_root), *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
            check=False,
        )

    inside = run("rev-parse", "--is-inside-work-tree")
    top_level = run("rev-parse", "--show-toplevel")
    if (
        inside.returncode != 0
        or inside.stdout.strip() != "true"
        or top_level.returncode != 0
        or Path(top_level.stdout.strip()).resolve() != source_root.resolve()
    ):
        raise RuntimeError(f"Hermes source is not a Git checkout: {source_root}")
    status = run("status", "--porcelain")
    branch = run("branch", "--show-current")
    head = run("rev-parse", "HEAD")
    if any(result.returncode != 0 for result in (status, branch, head)):
        raise RuntimeError(f"Could not inspect Hermes Git checkout: {source_root}")
    return GitState(
        clean=not status.stdout.strip(),
        branch=branch.stdout.strip(),
        head=head.stdout.strip(),
    )
