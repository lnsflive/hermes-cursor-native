"""Cursor model-provider setup: browser OAuth, bridge check, live catalog."""

from __future__ import annotations


def _login_cursor_oauth(*_args, force_new_login: bool = False, **_kwargs) -> None:
    from .cursor_sdk_auth import (
        clear_sdk_credentials,
        login,
        read_sdk_credentials,
        save_sdk_credentials,
    )

    backup = read_sdk_credentials() if force_new_login else None

    def on_url(url: str) -> None:
        print(f"Open this URL to log in to Cursor:\n{url}")

    if force_new_login:
        clear_sdk_credentials()
    try:
        login(on_login_url=on_url, on_status=print)
    except (Exception, KeyboardInterrupt):
        if backup is not None:
            expires = backup.get("apiKeyExpiresAtMs")
            save_sdk_credentials(
                backend_url=str(backup.get("backendUrl") or ""),
                api_key=str(backup["apiKey"]),
                api_key_expires_at_ms=int(expires) if isinstance(expires, (int, float)) else None,
                email=str(backup.get("email") or ""),
            )
        raise


def _cursor_logged_in() -> bool:
    from .cursor_sdk_auth import resolve_cursor_api_key

    return bool(resolve_cursor_api_key()[0])


def _ensure_bridge() -> str | None:
    from hermes_cli.config import load_config

    from .cursor_bridge_transport import CursorBridgeError, download_bridge, resolve_bridge_command

    bridge_settings = load_config().get("cursor_bridge") or {}
    configured_command = str(bridge_settings.get("command") or "")
    bridge_command = resolve_bridge_command(configured_command)
    if bridge_command:
        return bridge_command

    print("  The Cursor SDK bridge (cursor-sdk-bridge) is not installed.")
    try:
        answer = input("  Download it now? [Y/n]: ").strip().lower()
    except (KeyboardInterrupt, EOFError):
        print()
        answer = "n"
    if answer in {"", "y", "yes"}:
        try:
            return download_bridge(str(bridge_settings.get("download_version") or ""))
        except CursorBridgeError as exc:
            print(f"  ⚠ {exc}")
    print("  Continuing without the bridge — install later with")
    print("  `pip install cursor-sdk` or set cursor_bridge.command in config.yaml.")
    return None


def _cursor_model_list(api_key: str, bridge_command: str | None) -> list[str]:
    from hermes_cli.models import _PROVIDER_MODELS

    provider_id = "cursor"
    model_list: list[str] = []
    if bridge_command and api_key:
        try:
            from .cursor_bridge_client import CursorBridgeClient

            print("  Fetching your Cursor model catalog...")
            client = CursorBridgeClient(api_key=api_key)
            try:
                catalog = client.list_models()
            finally:
                client.close()
            model_list = [str(m.get("id") or "").strip() for m in catalog]
            model_list = [m for m in model_list if m]
            if model_list:
                print(f"  Found {len(model_list)} model(s) on your Cursor account")
        except Exception as exc:
            print(f"  ⚠ Could not fetch the live catalog: {exc}")

    if not model_list:
        from providers import get_provider_profile

        profile = get_provider_profile(provider_id)
        model_list = list(_PROVIDER_MODELS.get(provider_id, []))
        if not model_list and profile is not None:
            model_list = list(profile.fallback_models or ())
        if model_list:
            print('  Showing default models — use "Enter custom model name" if')
            print("  you do not see the model you want.")
    return model_list


def model_flow_cursor(config, current_model="", args=None):  # noqa: ANN001, ARG001
    """OAuth-first Cursor setup for ``hermes model`` and the setup wizard."""
    from hermes_cli.auth import PROVIDER_REGISTRY, _prompt_model_selection
    from hermes_cli.model_setup_flows_common import _activate_provider_model, _oauth_gate, _say

    del config

    provider_id = "cursor"
    pconfig = PROVIDER_REGISTRY[provider_id]
    effective_base = pconfig.inference_base_url

    _say(
        "  Cursor runs Hermes turns through the official Cursor SDK bridge.",
        "  Sign in with your Cursor account in the browser — usage bills to",
        "  your Cursor plan. Hermes never proxies or resells Cursor inference.",
        "",
    )

    if not _oauth_gate(
        _cursor_logged_in(),
        "Cursor",
        _login_cursor_oauth,
        PROVIDER_REGISTRY[provider_id],
        fresh_name="Cursor",
        recheck=_cursor_logged_in,
    ):
        return

    from .cursor_sdk_auth import resolve_cursor_api_key

    api_key, _source = resolve_cursor_api_key()
    bridge_command = _ensure_bridge()
    model_list = _cursor_model_list(api_key, bridge_command)

    if model_list:
        selected = _prompt_model_selection(
            model_list,
            current_model=current_model,
            confirm_provider=provider_id,
            confirm_base_url=effective_base,
            confirm_api_key=api_key,
        )
    else:
        try:
            selected = input("Model name: ").strip()
        except (KeyboardInterrupt, EOFError):
            selected = None

    _activate_provider_model(
        selected,
        provider_id,
        effective_base,
        f"Default model set to: {selected} (via {pconfig.name})",
    )
    if selected:
        print("  Usage is billed to your own Cursor subscription.")
