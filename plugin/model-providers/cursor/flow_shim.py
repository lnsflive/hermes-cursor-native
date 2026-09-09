"""Dispatch Cursor setup through OAuth without touching ``main._PROVIDER_MODEL_FLOWS``."""

from __future__ import annotations

import logging
import sys

logger = logging.getLogger(__name__)
_FLOW_WRAPPED = False


def install_model_flow_wrapper() -> bool:
    """Wrap ``_model_flow_api_key_provider``; cursor uses OAuth, others unchanged."""
    global _FLOW_WRAPPED
    if _FLOW_WRAPPED:
        return True
    try:
        import hermes_cli.model_setup_flows as flows_mod
    except Exception as exc:
        logger.debug("cursor flow wrapper unavailable: %s", exc)
        return False

    original = flows_mod._model_flow_api_key_provider
    if getattr(original, "_cursor_flow_wrapper", False):
        _FLOW_WRAPPED = True
        return True

    def _model_flow_api_key_provider(config, provider_id, current_model=""):  # noqa: ANN001
        if provider_id == "cursor":
            from .setup_flow import model_flow_cursor

            model_flow_cursor(config, current_model=current_model)
            return
        return original(config, provider_id, current_model=current_model)

    _model_flow_api_key_provider._cursor_flow_wrapper = True  # type: ignore[attr-defined]
    flows_mod._model_flow_api_key_provider = _model_flow_api_key_provider
    _patch_main_alias(_model_flow_api_key_provider)
    _FLOW_WRAPPED = True
    return True


def _patch_main_alias(wrapper) -> None:  # noqa: ANN001
    main_mod = sys.modules.get("hermes_cli.main")
    if main_mod is None:
        return
    if getattr(main_mod, "_model_flow_api_key_provider", None) is not wrapper:
        main_mod._model_flow_api_key_provider = wrapper
