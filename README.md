# AgentSurface

**An ephemeral OS for any agent.** Instead of dumping text, an agent emits a flat declarative JSON blueprint that renders as a live interface — forms, dashboards, sliders, task boards — on a self-contained, CSP-safe HTML canvas. The user acts; the renderer emits an intent envelope; the envelope pastes back into the agent. Close the tab and the surface dissolves.

## Why

Markdown replies are the bottleneck. Google Research ("Generative UI: LLMs are Effective UI Generators") showed humans prefer functional generated interfaces over markdown 83% of the time. But raw HTML/JS generation is a security catastrophe, and hosted SDK frameworks (Vercel RSC, CopilotKit, Tambo) need a running app. AgentSurface gives *every* agent the surface — zero backend, zero dependencies, zero executable code in the payload.

## Architecture (A2UI lineage)

- **Flat adjacency list** — components reference children by id; never nested. Kills the hallucinated-closing-bracket failure mode.
- **Intent firewall** — buttons declare whitelisted intent strings; the renderer blocks anything not declared at blueprint time. The LLM can arrange semantic controls but cannot express execution.
- **Event hydration** — the intent envelope (surface, intent, values, ts) is copied back into the agent's context; the loop continues.
- **Ephemeral by design** — no persistence, no server, no network calls. deleteSurface = close the tab.

## Repo contents

- `skill/SKILL.md` — how any agent uses this
- `skill/references/dsl-spec.md` — the full contract (types, gates, envelope, security model)
- `skill/scripts/validate_blueprint.py` — 8-gate validator (flatness, whitelist, binds, intents)
- `skill/templates/surface-template.html` — the CSP-safe renderer
- `demo/index.html` — live demo: audit scope picker (open it in a browser)

## Demo

Open `demo/index.html` in any browser — or see it served at the GitHub Pages URL of this repo.

## License

Apache-2.0-aligned, mirroring A2UI's posture.
