"""Picker credential detection for Cursor SDK login."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)
_PICKER_INSTALLED = False


def _cursor_slug_keys() -> tuple[str, ...]:
    keys = {"cursor", "cursor-sdk", "cursor-agent"}
    try:
        from hermes_cli.models import _PROVIDER_ALIASES

        keys.update(alias for alias, canon in _PROVIDER_ALIASES.items() if canon == "cursor")
    except Exception:
        pass
    return tuple(keys)


def _cursor_has_sdk_credentials() -> bool:
    from .cursor_sdk_auth import resolve_cursor_api_key

    return bool(resolve_cursor_api_key()[0])


def install_picker_credential_shim() -> bool:
    """Teach canonical inventory rows that SDK login counts as authenticated."""
    global _PICKER_INSTALLED
    if _PICKER_INSTALLED:
        return True
    try:
        import hermes_cli.model_switch_providers as picker_mod
    except Exception as exc:
        logger.debug("cursor picker credential shim unavailable: %s", exc)
        return False

    original = picker_mod._auth_store_has_provider
    cursor_keys = set(_cursor_slug_keys())

    def _auth_store_has_provider(*keys: str) -> bool:
        if original(*keys):
            return True
        lowered = {str(k).strip().lower() for k in keys if k}
        if lowered & cursor_keys:
            return _cursor_has_sdk_credentials()
        return False

    picker_mod._auth_store_has_provider = _auth_store_has_provider
    picker_mod._cursor_cred_shim_installed = True
    _PICKER_INSTALLED = True
    return True
