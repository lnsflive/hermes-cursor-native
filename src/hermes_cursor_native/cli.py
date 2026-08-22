"""Command-line interface for Hermes Cursor Native."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable, Sequence
from dataclasses import asdict
from pathlib import Path

from .discovery import AmbiguousRuntimeError, DiscoveryError, Runtime, select_runtime
from .install_plan import (
    GitState,
    InstallBlockedError,
    InstallManifest,
    InstallPlan,
    build_install_plan,
)
from .installer import InstallerError, execute_install_plan
from .manifest import default_manifest_path, load_manifest, package_data_root
from .preflight import detect_architecture, probe_git_state, provider_installation_complete
from .rendering import render_runtime_table
from .system_discovery import discover_system


def _runtime_dict(runtime: Runtime) -> dict[str, object]:
    payload = asdict(runtime)
    payload["surfaces"] = list(runtime.surfaces)
    payload["home"] = str(runtime.home)
    payload["source_root"] = str(runtime.source_root) if runtime.source_root else None
    payload["executable"] = str(runtime.executable) if runtime.executable else None
    return payload


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="hermes-cursor-native",
        description="Install and manage the native Cursor provider for Hermes Agent.",
    )
    subcommands = parser.add_subparsers(dest="command", required=True)
    discover = subcommands.add_parser("discover", help="Find Hermes runtimes without changing them")
    discover.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    install = subcommands.add_parser("install", help="Plan or install the Cursor provider")
    install.add_argument("--runtime", help="Explicit runtime id from `discover`")
    install.add_argument("--profile", default="default", help="Hermes profile to configure")
    install.add_argument("--manifest", type=Path, default=default_manifest_path())
    install.add_argument(
        "--dry-run", action="store_true", help="Print every operation; write nothing"
    )
    install.add_argument("--yes", action="store_true", help="Approve the displayed plan")
    install.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    discover: Callable[[], list[Runtime]] = discover_system,
    manifest_loader: Callable[[Path], InstallManifest] = load_manifest,
    git_probe: Callable[[Path], GitState] = probe_git_state,
    architecture: Callable[[], str] = detect_architecture,
    apply_plan: Callable[[InstallPlan], None] | None = None,
    input_func: Callable[[str], str] = input,
) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "discover":
        runtimes = discover()
        if args.json:
            print(json.dumps([_runtime_dict(runtime) for runtime in runtimes], indent=2))
        else:
            print(render_runtime_table(runtimes))
        return 0
    if args.command == "install":
        if args.yes and not args.runtime:
            raise InstallBlockedError(
                "Non-interactive installation requires an explicit --runtime"
            )
        runtimes = discover()
        try:
            runtime = select_runtime(runtimes, requested=args.runtime)
        except AmbiguousRuntimeError:
            if args.yes:
                raise
            print(render_runtime_table(runtimes))
            requested = input_func("Runtime id to install into: ").strip()
            runtime = select_runtime(runtimes, requested=requested)
        manifest = manifest_loader(args.manifest)
        if runtime.source_root is None:
            raise InstallBlockedError(f"Runtime {runtime.runtime_id!r} has no source checkout")
        plan = build_install_plan(
            runtime=runtime,
            manifest=manifest,
            profile=args.profile,
            git_state=git_probe(Path(runtime.source_root)),
            architecture=architecture(),
            provider_installed=provider_installation_complete(
                Path(runtime.source_root), manifest.provider_file_sha256
            ),
            profile_exists=(
                args.profile == "default"
                or (Path(runtime.home) / "profiles" / args.profile).is_dir()
            ),
        )
        if args.json:
            print(plan.to_json())
        else:
            print(f"Install plan for {runtime.runtime_id} / profile {args.profile}")
            for index, operation in enumerate(plan.operations, 1):
                print(f"  {index}. {operation.kind}: {operation.description}")
        if args.dry_run:
            return 0
        if not args.yes:
            approved = input_func("Apply this plan? [y/N]: ").strip().casefold()
            if approved not in {"y", "yes"}:
                return 1
        if apply_plan is None:
            def apply_plan(selected_plan: InstallPlan) -> None:
                execute_install_plan(
                    selected_plan,
                    package_root=package_data_root(),
                    approved=True,
                )
        apply_plan(plan)
        return 0
    return 2


def entrypoint(argv: Sequence[str] | None = None) -> int:
    try:
        return main(argv)
    except (DiscoveryError, InstallBlockedError, InstallerError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(entrypoint())
