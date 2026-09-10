# Architecture

## Current: plugin-only on stock Hermes

```text
Hermes Agent (stock checkout, no core patches)
  -> $HERMES_HOME/plugins/model-providers/cursor/
  -> ProviderProfile.create_client -> CursorBridgeClient
  -> official cursor-sdk-bridge (sdk.v1 / Connect)
  -> Cursor model

Cursor custom-tool callback
  -> Hermes tool call
  -> Hermes approval/hooks/execution
  -> tool result returned to Cursor
```

The installer deploys:

1. **Plugin** — `plugin/model-providers/cursor/` into `$HERMES_HOME/plugins/model-providers/cursor/`
2. **Bridge** — verified `cursor-sdk-bridge` tarball under `$HERMES_HOME/cursor-sdk-bridge/`
3. **Profile config** — `cursor_bridge.*` keys in the targeted Hermes profile (additive; default model unchanged unless `--switch-default-model`)

An **auth shim** inside the plugin extends stock Hermes `_resolve_api_key_provider_secret` so browser OAuth in `~/.cursor/sdk/auth.json` is visible to `hermes auth status`, runtime resolution, and chat — without patching Hermes core.

## Capability checks (pre-install)

Before any write, `install` runs **behavioral probes** against the selected runtime:

| Probe | What it proves |
|-------|----------------|
| `plugin_seam` | `ProviderProfile.create_client` exists on stock Hermes |
| `provider_client_seam` | Hermes routes provider-supplied clients |
| `plugin_registered` | Cursor plugin loads from a temp `$HERMES_HOME` |
| `client_contract` | Plugin client exposes skip flags; offline streaming/tool callback contract passes |

These are **not** end-to-end evidence. They do not contact Cursor inference or prove OAuth.

## End-to-end verification (post-OAuth, required)

After the user completes browser OAuth for the estate's OS user:

1. `hermes auth status cursor` → logged in
2. `hermes-cursor-native status --json` → `model_catalog_count` > 0, `chat_probe` → `runtime_credentials_ok`
3. Live chat smoke — `hermes chat --provider cursor` with a short prompt
4. Hermes-owned tool call — terminal or equivalent tool executed inside Hermes's loop (not bridge harness mode)

Mocked client-contract probes in CI complement but do not replace live receipts.

## Historical patch mode

Historical versioned patches are preserved in Git history, not shipped in current installations.

## Trust boundary

- Hermes owns session, memory, tools, approvals, hooks, profiles, and delivery.
- Cursor owns inference and model-side reasoning.
- Cursor built-in tools are disabled in normal provider mode (`cursor_bridge.tool_mode: loop`).
- OAuth credentials stay in Cursor's SDK credential store and never enter plan JSON or LLM context.
