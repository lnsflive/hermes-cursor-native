---
name: hermes-cursor-native
description: Install Cursor models as a native Hermes provider.
version: 0.1.0
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

- Install Composer, Grok, or the Cursor catalog into Hermes.
- Diagnose provider, OAuth, bridge, profile, or update-survival failures.
- Replicate the provider to another Hermes backend/profile.

## Prerequisites

- Hermes Agent 0.20.5 for the alpha patch series.
- Git-backed Hermes source checkout.
- Cursor account eligible for SDK OAuth.
- User approval for the exact runtime/profile.

## Procedure

1. Run `hermes-cursor-native discover`; account for every runtime.
2. Run `hermes-cursor-native install --dry-run --runtime <id> --profile <name>`.
3. Show the plan and obtain approval.
4. Run `hermes-cursor-native install --runtime <id> --profile <name> --yes`.
5. Let the user complete OAuth without exposing credential material.
6. Verify Composer, Grok, auto routing, and one Hermes-owned tool call.
7. Report backup/deployment branches and rollback instructions.

## Pitfalls

- Desktop shell path is not the backend path.
- `%USERPROFILE%\.hermes`, `%LOCALAPPDATA%\hermes`, and WSL are separate.
- Existing sessions must restart after provider/config changes.
- Alpha patch mode needs update reconciliation.

## Verification

Success requires all installer verification steps to pass; provider discovery alone is insufficient.
