"""Cursor subscription model provider (plugin-local bridge transport)."""

from providers import register_provider
from providers.base import ProviderProfile


class CursorProfile(ProviderProfile):
    """Cursor subscription — local sdk.v1 bridge subprocess, no REST catalog."""

    def create_client(self, **client_kwargs):
        from .cursor_bridge_client import CursorBridgeClient

        return CursorBridgeClient(**client_kwargs)

    def fetch_models(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        timeout: float = 8.0,
    ) -> list[str] | None:
        del base_url, timeout
        if not api_key:
            return None
        try:
            from .cursor_bridge_client import CursorBridgeClient
            from .cursor_bridge_transport import resolve_bridge_command

            if not resolve_bridge_command():
                return None
            client = CursorBridgeClient(api_key=api_key)
            try:
                models = client.list_models()
            finally:
                client.close()
            ids = [str(m.get("id") or "").strip() for m in models]
            return [m for m in ids if m] or None
        except Exception:
            return None


cursor = CursorProfile(
    name="cursor",
    aliases=("cursor-sdk", "cursor-agent"),
    display_name="Cursor",
    description="Cursor subscription (Composer + catalog via the Cursor SDK bridge)",
    signup_url="https://cursor.com/dashboard",
    api_mode="chat_completions",
    env_vars=("CURSOR_API_KEY",),
    base_url="sdkbridge://cursor",
    auth_type="api_key",
    supports_health_check=False,
    fallback_models=(
        "auto",
        "composer-2.5",
    ),
)

register_provider(cursor)
