# Cursor provider for Hermes

Add **Cursor** to Hermes's provider menu and use your account's Composer, Claude, GPT, Gemini, and other available models. Hermes keeps control of its own tools and sessions; requests run through the official Cursor SDK bridge.

This is a **model-provider plugin**, not a Hermes fork. It does not patch Hermes source, contain credentials, or require a particular Hermes version number.

## Install

With Hermes already installed:

```bash
hermes plugins install https://github.com/lnsflive/hermes-cursor-native --enable
hermes model
```

Review Hermes’s plugin trust prompt during installation.

Select **Cursor** near the bottom of the provider menu. Reuse an existing compatible credential, or sign in through the browser. If needed, setup offers to download the verified SDK bridge. Then choose a model from your account's live catalog.

Restart any Hermes process that was already running before installing/updating. Run installation and login as the OS user who runs Hermes. Repeat for each machine or separate Hermes home you use.

After authentication, Cursor models also appear in the in-chat `/model` picker and model inventory. Installation preserves your existing default model until you choose a replacement.

## Existing authentication

Credentials are resolved in this order:

1. `CURSOR_API_KEY` from the environment or Hermes `.env`.
2. A valid SDK browser login in the current user's `~/.cursor/sdk/auth.json`.
3. An API key, if present in that same user's file-backed Cursor Agent CLI store.
4. Otherwise, `hermes model` → **Cursor** opens browser login.

CLI **browser login is not automatically an SDK API key**. The plugin only reuses the CLI's explicit `apiKey` field; it never treats OAuth access/refresh tokens as API keys. Keychain-only or changed CLI stores fall back to browser login. No credential is copied between users, hosts, or stores.

See [Cursor's SDK authentication documentation](https://cursor.com/docs/sdk/python#authentication). Model availability and usage follow your Cursor account; this plugin does not provide a free inference service.

## Compatibility

Compatibility depends on Hermes's provider/client interfaces, not its version string. The plugin adapts provider registration, SDK credential discovery, model selection, and OAuth setup without editing core files.

That does **not** guarantee compatibility with every past or future Hermes release. CI checks the supported baseline and current upstream; if Hermes changes an interface, the plugin may need updating. The optional installer probes the selected runtime before writing files. The SDK bridge is separately pinned and SHA256-verified because its wire protocol is a real dependency.

## Optional installer

For runtimes without native plugin installation, or explicit runtime selection:

```bash
uvx --from git+https://github.com/lnsflive/hermes-cursor-native@main hermes-cursor-native install
```

This installs the same provider under `$HERMES_HOME/plugins/model-providers/cursor` and the SDK bridge. Use either native installation or this installer for a given home, rather than installing duplicate copies.

The shell/PowerShell bootstraps also install the current plugin code. Set `HCN_REF` to a reviewed commit/tag to pin a deployment. [Installation details](docs/installation.md).

## Development

```bash
uv sync --extra dev
uv run pytest
uv run ruff check .
uv build
```

Set `HERMES_AGENT_ROOT` to a runnable Hermes checkout to run integration tests. Those tests cover normal import orders, browser-login dispatch, authenticated model pickers, and Hermes-owned tool callbacks using isolated test credentials. Live account checks are separate.

## Attribution

The provider originated in [NousResearch/hermes-agent PR #81502](https://github.com/NousResearch/hermes-agent/pull/81502), authored by Cursor Agent and Ethan Troy. Authorship and historical patches remain in Git history. See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) and [LICENSE](LICENSE).
