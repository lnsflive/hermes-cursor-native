# Hermes Cursor Native

Use Composer 2.5, Grok 4.6, Claude, GPT, Gemini, and your full Cursor model catalog as a native provider for [Hermes Agent](https://github.com/NousResearch/hermes-agent) chats, profiles, gateways, and bots.

**Browser OAuth · official Cursor SDK bridge · Hermes-owned tools · profiles and gateways · Windows-first alpha**

> [!WARNING]
> This repository is an early alpha. Version `0.1.0a1` supports a tested Hermes 0.20.5 patch path. Run discovery and `install --dry-run` before applying anything.

Hermes Cursor Native is independent and community-maintained. It is not affiliated with or endorsed by Nous Research or Cursor/Anysphere.

## Why this exists

Existing integrations generally make Cursor a delegated coding tool, wrap Cursor CLI in a proxy, or require a manually managed dashboard key. Hermes Cursor Native targets a different contract:

```text
Hermes profile
  -> provider: cursor
  -> official Cursor sdk.v1 bridge
  -> structured custom-tool callback
  -> Hermes executes tools, approvals, hooks, memory, and sessions
  -> Cursor consumes the real tool result
```

## Capabilities

- Browser PKCE OAuth via `hermes cursor login`
- Full live Cursor account model catalog
- Composer 2.5, Grok 4.6, and account-available Cursor models
- Normal Hermes `model.provider=cursor`
- Structured Hermes-owned tool execution
- Profile, gateway, cron, memory, skills, plugin, and session compatibility
- Runtime discovery across current Windows, legacy Windows, WSL, explicit source/Desktop overrides, and the checkout behind the active PATH launcher
- Versioned patch series with original authorship preserved
- Verified bridge downloads with SHA256 enforcement
- Maintained deployment branch and rollback reference

## Cursor-powered Hermes bots

Once installed, `provider: cursor` works anywhere a normal Hermes model provider works. Existing Hermes profiles and messaging bots can use Cursor models while retaining their own identity, memory, skills, tools, sessions, and gateway configuration—including Telegram, Discord, Slack, WhatsApp, and other Hermes platforms.

Hermes Cursor Native does **not** create a bot, named profile, or messaging connection. It installs and configures the provider for the profile you explicitly target. Bot/profile creation remains a normal Hermes workflow, so the same installation can support one existing bot or several independently configured profiles.

## One-command install

These commands become active after this repository is published.

### Windows PowerShell

```powershell
irm https://raw.githubusercontent.com/lnsflive/hermes-cursor-native/v0.1.0-alpha.1/install.ps1 | iex
```

### macOS, Linux, or WSL

```bash
curl -fsSL https://raw.githubusercontent.com/lnsflive/hermes-cursor-native/v0.1.0-alpha.1/install.sh | bash
```

The command installs the management CLI, discovers Hermes runtimes, displays the exact plan, asks for the target and approval, opens Cursor OAuth, and runs verification. It does not create a new Hermes bot or profile.

Release tags are the supported install source. Development builds require an explicit `HCN_REF` or `HCN_REPO` override.

## Agent-driven install

Tell a capable agent:

```text
Install Hermes Cursor Native from https://github.com/lnsflive/hermes-cursor-native.
Read INSTALL_AGENT.md first. Show me every detected Hermes runtime and the exact
plan, then wait for approval. Never print or copy OAuth credentials.
```

## Local development

```powershell
git clone https://github.com/lnsflive/hermes-cursor-native
cd hermes-cursor-native
uv venv --python 3.11 .venv
uv pip install --python .venv/Scripts/python.exe -e ".[dev]"
.venv/Scripts/hermes-cursor-native.exe discover
.venv/Scripts/hermes-cursor-native.exe install --dry-run --runtime windows-current
```

POSIX uses `.venv/bin/...` instead.

## Runtime discovery

```text
hermes-cursor-native discover
hermes-cursor-native discover --json
```

The installer treats each Hermes estate independently. It never merges `%USERPROFILE%\.hermes`, `%LOCALAPPDATA%\hermes`, WSL, named profiles, or remote backends automatically.

Remote/cloud/SSH Desktop registry discovery is planned and is not implemented in this alpha. Install on remote backends by running the installer on that host.

See [Runtime discovery](docs/runtime-discovery.md).

Operational references:

- [Architecture](docs/architecture.md)
- [Update survival and rollback](docs/update-survival.md)
- [Troubleshooting](docs/troubleshooting.md)
- [Existing approaches](docs/comparison.md)
- [Third-party notices](THIRD_PARTY_NOTICES.md)

## Install workflow

```text
hermes-cursor-native install --dry-run --runtime windows-current --profile default
hermes-cursor-native install --runtime windows-current --profile default
```

For agent/CI use, both target and approval must be explicit:

```text
hermes-cursor-native install --runtime windows-current --profile default --yes
```

## Verification

A successful install checks:

1. Cursor provider registration through successful chats
2. bridge path and SHA256
3. OAuth login completion
4. Composer 2.5 response marker
5. Grok 4.6 response marker
6. automatic Cursor routing response marker
7. Hermes-owned terminal tool execution using a hidden random file nonce

## Update model

Alpha patch mode keeps Cursor commits on `cursor-provider-deployed` and configures:

```yaml
updates:
  parked_branch_strategy: update_in_place
```

Upstream merges preserve the provider when clean. Conflicts stop for reconciliation. Do not use `hermes update --switch-branch` on a patched installation.

The long-term target is a stock-Hermes provider service that requires no core patch. See [Architecture](docs/architecture.md).

## Provenance

The provider implementation originates from [NousResearch/hermes-agent PR #81502](https://github.com/NousResearch/hermes-agent/pull/81502), authored by Cursor Agent and Ethan Troy. This project preserves commit authorship and adds packaging, Windows support, runtime discovery, update safety, installation, rollback, and cross-harness documentation.

## Security

Read [SECURITY.md](SECURITY.md) before installing. The project never asks an LLM to handle OAuth credentials and never copies auth stores between Windows, WSL, users, or remote hosts.

## License

MIT. Third-party components retain their own licenses and trademarks.
