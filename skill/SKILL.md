---
name: agent-surface
description: Gives any agent a generative UI surface — emit a declarative JSON blueprint that renders on a self-contained, CSP-safe HTML canvas with a whitelisted intent router. Turn "here's my text reply" into "here's the interface I built for this moment."
version: 0.1.0
license: Apache-2.0 (mirrors A2UI posture)
---

# AgentSurface — ephemeral OS per agent

## When to use
- The answer is not text — it's a dashboard, form, task board, comparison table, or control panel.
- The user should interact (pick, slide, fill, toggle) instead of reading a wall of markdown.
- You need structured input back (a form beats "reply with your choices as text").

## When NOT to use
- The answer is a simple factual reply.
- The interaction needs live bidirectional transport (this is submit-back-as-text, not WebSocket).
- You'd need executable JS in the payload — never. Blueprint is data, not code.

## The flow (Genius Loop compliant)

1. **Clarify** — decide the surface serves this moment (forms, dashboards, task boards, scopes).
2. **Blueprint** — emit a flat AgentSurface JSON blueprint (see `references/dsl-spec.md`). Flat adjacency list only — NEVER nest component trees.
3. **Validate** — run `scripts/validate_blueprint.py` on the blueprint. Zero tolerance: unknown types, nested trees, unbound intents, or non-whitelisted intent strings fail.
4. **Render** — copy `templates/surface-template.html`, replace `__BLUEPRINT__` with the validated JSON, save as `surface-<slug>.html`, upload as a public file, share the URL.
5. **Hydrate** — the user interacts; the renderer emits an intent envelope (JSON text). They paste it back to you. Ingest the values, continue the loop. A new moment = a new surface. Old ones dissolve.

## Core rules
- **Data, not code.** The blueprint is declarative JSON. No scripts, no eval, no executable JS in the payload.
- **Flat, not nested.** Components are a flat list; hierarchy is by id reference (children arrays of ids). Nested trees = hallucination magnet = rejected by the validator.
- **Intent firewall.** Every action declares its intent string at blueprint time. The renderer only fires intents that exist in the blueprint's own `intents` whitelist. Buttons can't invent behavior.
- **CSP-safe.** Renderer uses textContent everywhere, zero external scripts, zero network calls, inline styles only. Safe to open in a sandboxed iframe.
- **Ephemeral by design.** No persistence, no accounts, no server. Closing the tab is deleteSurface.

## A2UI lineage (why these choices)
Mirrors Google's A2UI protocol primitives — createSurface / updateComponents / updateDataModel / deleteSurface — compressed into a single static blueprint for one-shot surfaces. Drops all vendor SDKs, transports, and cloud dependencies deliberately. Layer-agnostic: works identically whether the model serves via vLLM, HF Transformers, or Ollama, and whether orchestration is LangGraph, CrewAI, or nothing at all.

## Files
- `references/dsl-spec.md` — the full DSL contract (types, props, actions, envelope)
- `templates/surface-template.html` — CSP-safe renderer; inject blueprint at `__BLUEPRINT__`
- `scripts/validate_blueprint.py` — validator; run before every render
