"""Command-line interface for Hermes Cursor Native."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Callable, Sequence
from dataclasses import asdict, replace
from pathlib import Path

from .discovery import AmbiguousRuntimeError, DiscoveryError, Runtime, select_runtime
from .install_plan import InstallBlockedError, InstallPlan, build_install_plan
from .installer import (
    InstallerError,
    execute_install_plan,
    run_command,
    run_cursor_oauth,
)
from .manifest import InstallManifest, default_manifest_path, load_manifest, package_data_root
from .preflight import detect_architecture
from .rendering import render_runtime_table
from .system_discovery import discover_system
from .verify import collect_receipt, resolve_status_bridge


def _require_local_runtime(runtime: Runtime, command: str) -> None:
    if runtime.platform == "wsl" and os.name == "nt":
        raise InstallerError(
            f"Run {command} inside the selected WSL distribution ({runtime.runtime_id}); "
            "Windows cannot execute this runtime directly."
        )


def _resolved_home(path: Path | str) -> Path:
    resolved = Path(path).expanduser()
    if not resolved.is_absolute():
        resolved = resolved.resolve()
    return resolved


def _apply_home_override(runtime: Runtime, hermes_home: str | None) -> Runtime:
    home = _resolved_home(hermes_home) if hermes_home else _resolved_home(runtime.home)
    return replace(runtime, home=home)


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
        description="Install and manage the Cursor model-provider plugin for Hermes Agent.",
    )
    subcommands = parser.add_subparsers(dest="command", required=True)

    discover = subcommands.add_parser("discover", help="Find Hermes runtimes without changing them")
    discover.add_argument("--json", action="store_true", help="Emit machine-readable JSON")

    install = subcommands.add_parser("install", help="Install the Cursor model-provider plugin")
    install.add_argument("--runtime", help="Explicit runtime id from `discover`")
    install.add_argument(
        "--hermes-home",
        help="Target HERMES_HOME for plugin/bridge writes (defaults to discovered runtime home)",
    )
    install.add_argument("--profile", default="default", help="Hermes profile to configure")
    install.add_argument("--manifest", type=Path, default=default_manifest_path())
    install.add_argument(
        "--dry-run", action="store_true", help="Print every operation; write nothing"
    )
    install.add_argument("--yes", action="store_true", help="Approve the displayed plan")
    install.add_argument(
        "--oauth",
        action="store_true",
        help="Launch interactive browser OAuth after install (skipped by default)",
    )
    install.add_argument(
        "--switch-default-model",
        action="store_true",
        help="Also switch the selected profile default model to Cursor",
    )
    install.add_argument("--json", action="store_true", help="Emit machine-readable JSON")

    login = subcommands.add_parser("login", help="Run Cursor browser OAuth on a Hermes host")
    login.add_argument("--runtime", help="Explicit runtime id from `discover`")
    login.add_argument("--hermes-home", help="Target HERMES_HOME for OAuth state")
    login.add_argument("--profile", default="default", help="Hermes profile context")

    status = subcommands.add_parser("status", help="Show plugin/auth receipts for a runtime")
    status.add_argument("--runtime", help="Explicit runtime id from `discover`")
    status.add_argument("--hermes-home", help="Target HERMES_HOME for receipt probes")
    status.add_argument("--profile", default="default", help="Hermes profile to inspect")
    status.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    return parser


def _select_runtime(
    runtimes: list[Runtime],
    *,
    requested: str | None,
    input_func: Callable[[str], str],
    yes: bool,
) -> Runtime:
    try:
        return select_runtime(runtimes, requested=requested)
    except AmbiguousRuntimeError:
        if yes and not requested:
            raise
        print(render_runtime_table(runtimes))
        runtime_id = input_func("Runtime id: ").strip()
        return select_runtime(runtimes, requested=runtime_id)


def main(
    argv: Sequence[str] | None = None,
    *,
    discover: Callable[[], list[Runtime]] = discover_system,
    manifest_loader: Callable[[Path], InstallManifest] = load_manifest,
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

    runtimes = discover()

    if args.command == "status":
        runtime = _apply_home_override(
            _select_runtime(
                runtimes,
                requested=args.runtime,
                input_func=input_func,
                yes=bool(args.runtime),
            ),
            getattr(args, "hermes_home", None),
        )
        _require_local_runtime(runtime, "status")
        bridge, notes = resolve_status_bridge(runtime, args.profile)
        receipt = collect_receipt(runtime, bridge_path=bridge, profile=args.profile, notes=notes)
        if args.json:
            print(receipt.to_json())
        else:
            print(f"Host: {receipt.host}")
            print(f"Plugin installed: {receipt.plugin_installed} ({receipt.plugin_path})")
            print(f"Bridge installed: {receipt.bridge_installed} ({receipt.bridge_path})")
            print(f"Auth: cursor {receipt.auth_status}")
            if receipt.model_catalog_count is not None:
                print(f"Model catalog count: {receipt.model_catalog_count}")
            print(f"Contract checks: {receipt.contract_checks}")
        return 0

    if args.command == "login":
        runtime = _apply_home_override(
            _select_runtime(
                runtimes,
                requested=args.runtime,
                input_func=input_func,
                yes=bool(args.runtime),
            ),
            getattr(args, "hermes_home", None),
        )
        _require_local_runtime(runtime, "login")
        hermes = Path(runtime.executable)  # type: ignore[arg-type]
        source = Path(runtime.source_root) if runtime.source_root else Path(".")
        run_cursor_oauth(run_command, hermes, source, Path(runtime.home), package_data_root())
        return 0

    if args.command == "install":
        if args.yes and not args.runtime:
            raise InstallBlockedError("Non-interactive installation requires an explicit --runtime")
        runtime = _apply_home_override(
            _select_runtime(
                runtimes,
                requested=args.runtime,
                input_func=input_func,
                yes=args.yes,
            ),
            getattr(args, "hermes_home", None),
        )
        manifest = manifest_loader(args.manifest)
        plan = build_install_plan(
            runtime=runtime,
            manifest=manifest,
            profile=args.profile,
            architecture=architecture(),
            profile_exists=(
                args.profile == "default"
                or (Path(runtime.home) / "profiles" / args.profile).is_dir()
            ),
            switch_default_model=args.switch_default_model,
            run_oauth=args.oauth,
        )
        if args.json:
            print(plan.to_json(), file=sys.stdout if args.dry_run else sys.stderr)
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
                result = execute_install_plan(
                    selected_plan,
                    package_root=package_data_root(),
                    approved=True,
                )
                print(result.receipt.to_json())

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
