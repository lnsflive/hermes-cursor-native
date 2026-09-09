---
name: hermes-cursor-native
description: Install Cursor models as a native Hermes provider plugin on stock Hermes.
version: 0.2.0
author: Jaime Gonzalez (lnsflive), Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [Hermes, Cursor, OAuth, Model Provider]
    related_skills: []
---

# Hermes Cursor Native

Install and verify the Cursor provider only when the user explicitly requests it. Do not use this skill merely to delegate coding work to Cursor CLI.

## When to Use

- Install Composer, Grok, or the Cursor catalog into Hermes on stock Agent (plugin-only).
- Diagnose provider, OAuth, bridge, profile, or capability-probe failures.
- Replicate the provider to another Hermes backend/profile or OS user home.

## Prerequisites

- Stock Hermes Agent with runnable executable and source checkout (0.21.x verified).
- Behavioral capability probes pass for the target runtime.
- Cursor account eligible for SDK OAuth.
- User approval for the exact runtime/profile/`HERMES_HOME`.

## Procedure

1. Run `hermes-cursor-native discover`; account for every runtime.
2. Run `hermes-cursor-native install --dry-run --runtime <id> --profile <name> [--hermes-home <path>]`.
3. Show the plan, capability results, and obtain approval.
4. Run `hermes-cursor-native install --runtime <id> --profile <name> --yes` as the intended OS user.
5. Let the user complete OAuth without exposing credential material. Do not duplicate an in-progress login.
6. **Live verify:** auth status, model catalog, chat smoke, one Hermes-owned tool call.
7. Report plugin/bridge paths, backups, and estates still logged out.

## Pitfalls

- Desktop shell path is not the backend path.
- `%USERPROFILE%\.hermes`, `%LOCALAPPDATA%\hermes`, and WSL are separate.
- Shared-host installs need `--hermes-home` and the correct OS user for ownership.
- Non-root users on shared `/usr/local/lib/hermes-agent` venvs need readable `site-packages`.
- Existing sessions must restart after provider/config changes.

## Verification

Success requires **live** post-OAuth receipts (auth, catalog, chat, Hermes tool). Offline capability probes and mocked client contracts alone are insufficient.
