# Existing Approaches

Hermes Cursor Native is not the first Cursor/Hermes integration. It targets a specific combination that existing projects do not currently package together: browser OAuth, official `sdk.v1`, native Hermes provider semantics, structured Hermes-owned tools, full catalog, and verified native Windows behavior.

| Project | Strength | Difference |
|---|---|---|
| Cursor-Plan2API | Broad OpenAI-compatible proxy and model catalog | CLI/sidecar translation rather than native sdk.v1 callbacks |
| hermes-cursor-harness | Rich SDK/ACP delegation and proposal workflows | Cursor is an inner tool/runtime, not the normal profile model |
| perspective0labs provider | OAuth and no core edits | Private Connect implementation and buffered/stubbed agentic behavior |
| ktutumi SDK provider | Official SDK, plugin/service update isolation | Manual key, Linux/macOS focus |
| StrawCoding provider | Simple provider plugin | Per-request CLI process and manual key |
| Hermes PR #81502 | Native architecture used here | Upstream PR, not standalone packaging |

The project should collaborate and preserve attribution rather than claim invention of the general idea.
