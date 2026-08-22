# Architecture

## Current alpha: maintained native patch

```text
Hermes Agent
  -> provider: cursor
  -> CursorBridgeClient
  -> official cursor-sdk-bridge (sdk.v1 / Connect)
  -> Cursor model

Cursor custom-tool callback
  -> Hermes tool call
  -> Hermes approval/hooks/execution
  -> tool result returned to Cursor
```

The alpha carries the manifest-listed versioned Hermes patch series on `cursor-provider-deployed`. The installer preserves authorship with `git am`, configures `updates.parked_branch_strategy=update_in_place`, and creates a rollback branch.

## Why patch mode exists

Hermes provider plugins can declare existing transports but cannot yet register this custom client/transport without core support. The patch adds the native transport, OAuth, model picker, cloud commands, and tool callback loop.

## Long-term target: stock-Hermes provider service

```text
Stock Hermes ProviderProfile plugin
  -> authenticated localhost adapter
  -> official sdk.v1 bridge
  -> Cursor
```

The external adapter must preserve structured Hermes tool calls, OAuth, model discovery, profiles, and gateways without modifying Hermes core. Until that is proven, the project labels patch mode alpha.

## Trust boundary

- Hermes owns session, memory, tools, approvals, hooks, profiles, and delivery.
- Cursor owns inference and model-side reasoning.
- Cursor built-in tools are disabled in normal provider mode.
- OAuth credentials stay in Cursor's SDK credential store and never enter plan JSON or LLM context.
