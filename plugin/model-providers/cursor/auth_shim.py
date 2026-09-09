"""Register Cursor OAuth/SDK credentials with stock Hermes auth resolution.

Stock Hermes only checks ``CURSOR_API_KEY`` for ``auth_type=api_key`` providers.
This shim extends ``_resolve_api_key_provider_secret`` so browser OAuth stored in
``~/.cursor/sdk/auth.json`` is visible to ``hermes auth status``, runtime
resolution, and ``hermes chat --provider cursor`` before the bridge client is
constructed. No credential values are logged.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)
_INSTALLED = False


def _resolve_cursor_secret() -> tuple[str, str]:
    from .cursor_sdk_auth import resolve_cursor_api_key

    return resolve_cursor_api_key()


def sync_provider_auth_registry(profile) -> bool:
    """Register a plugin profile with stock ``hermes_cli.auth.PROVIDER_REGISTRY``.

    ``register_provider()`` only updates ``providers``; ``hermes auth status`` reads
    ``PROVIDER_REGISTRY``. Must run after the profile object exists.
    """
    try:
        import hermes_cli.auth as auth_mod
    except Exception as exc:
        logger.debug("cursor auth registry sync unavailable: %s", exc)
        return False
    if profile.name not in auth_mod.PROVIDER_REGISTRY:
        auth_mod._register_plugin_provider(profile)
    return profile.name in auth_mod.PROVIDER_REGISTRY


def install_auth_shim() -> bool:
    """Patch Hermes auth resolution once; safe to call repeatedly."""
    global _INSTALLED
    if _INSTALLED:
        return True
    try:
        import hermes_cli.auth as auth_mod
    except Exception as exc:
        logger.debug("cursor auth shim unavailable: %s", exc)
        return False

    original = auth_mod._resolve_api_key_provider_secret

    def _resolve_api_key_provider_secret(provider_id: str, pconfig):  # noqa: ANN001
        if provider_id == "cursor":
            key, source = _resolve_cursor_secret()
            if key:
                return key, source
        return original(provider_id, pconfig)

    auth_mod._resolve_api_key_provider_secret = _resolve_api_key_provider_secret
    _INSTALLED = True
    return True
