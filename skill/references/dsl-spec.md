# AgentSurface DSL v0.1 — The Contract

Data, not code. Flat, not nested. Fire only whitelisted intents. Everything else is implementation detail.

## 1. Blueprint (top level)

```json
{
  "surface":   { "id": "...", "title": "...", "subtitle": "...", "width": "compact|wide" },
  "dataModel": { "<key>": "<initial value>" },
  "components": [ <component>, ... ],
  "intents":   [ "<intent-string>", ... ]
}
```

- `surface` — identity + framing. One surface, one moment.
- `dataModel` — initial state. Keys are referenced by bound components. This is A2UI's updateDataModel baked in statically.
- `components` — flat adjacency list. Hierarchy is expressed ONLY by `children: ["id", "id"]` references. NEVER nest an object inside another.
- `intents` — the firewall whitelist. An action whose intent is not in this list is invalid and must fail validation.

## 2. Component

```json
{ "id": "unique-id", "type": "Type", "props": { ... }, "children": ["other-id", ...] }
```

- `id` — REQUIRED, unique, stable. Doubles as the annotation anchor (see §5).
- `children` — ordered id references. Empty or omitted for leaves.
- Every component must be reachable from exactly one parent (or be the root). Cycles and orphans fail validation.

## 3. Component types (whitelist, v0.1)

| Type | Key props | Binds data |
|---|---|---|
| Stack | direction: column\|row, gap | — |
| Card | padding, tone: default\|accent\|warn | — |
| Text | text | — |
| Heading | text, level | — |
| Badge | text, tone | — |
| KeyValue | label, value | — |
| Stat | label, value, unit | — |
| Divider | — | — |
| Spacer | size | — |
| Image | src, alt | — |
| Table | columns: [{key,label}], rows: [{}], dense | — |
| BarChart | title, series: [{label,value}], unit | — |
| LineChart | title, points: [y...], labels: [x...] | — |
| ProgressBar | value, max, label | — |
| Form | — | container for inputs |
| TextField | label, placeholder, bind, required, multiline | dataModel[bind] |
| Select | label, options: [], bind | dataModel[bind] |
| Slider | label, min, max, step, bind | dataModel[bind] |
| Checkbox | label, bind | dataModel[bind] |
| Toggle | label, bind | dataModel[bind] |
| Button | label, action: {intent, payloadKeys: [bind...]} | fires intent |

Rules:
- `bind` references a `dataModel` key; initial value comes from dataModel. Unbound `bind` = validation failure.
- `Button.action.intent` MUST appear in top-level `intents`.
- `payloadKeys` list the binds whose current values ship in the envelope. Default: every bind in the same Form.

## 4. Intent envelope (the hydration loop)

When a Button fires, the renderer collects bound values and emits:

```json
{ "surface": "surface-id", "intent": "submit_scope", "values": { "<bind>": "<value>" }, "ts": "ISO-8601" }
```

Delivery: rendered in an on-page result panel with a one-click copy, plus `postMessage` to the parent window (for embedding hosts). User pastes envelope back to the agent; agent ingests and continues. That is the entire loop. No server.

## 5. annotate intent (Leaf-inspired anchored feedback)

Any user can reference an exact component id when requesting changes. Conventional form the agent accepts back:

```json
{ "surface": "...", "intent": "annotate", "values": { "target": "c4", "comment": "make this stat green if positive" } }
```

Because every element has a stable id, revisions anchor to components, not to a position in a chat blob. The agent re-emits the blueprint with the change — a new surface, same ids where unchanged. This is Leaf's collaboration model, sovereign edition: no platform, just addressable elements.

## 6. Validation gates (all must pass)

1. JSON parses.
2. `components` is a flat array — any component object containing a nested component object fails.
3. Every id unique; no orphans; no cycles; exactly one root (a component with no parent).
4. Every `type` is in the whitelist.
5. Every `bind` exists in `dataModel`.
6. Every `Button.action.intent` is in `intents`.
7. No props outside the documented set per type (typos are hallucination signatures — fail loudly).
8. `text` props are plain strings — the renderer displays them via textContent; markup injection is structurally impossible.

## 7. Renderer guarantees

- Single self-contained HTML file. Zero external scripts, zero network calls, zero eval.
- All text rendered with textContent — no innerHTML for user/model-supplied strings.
- Inline styles only; safe inside a CSP-sandboxed iframe.
- Ephemeral: closing the tab is deleteSurface. Nothing persists anywhere.

## 8. Component catalog (grouped by purpose — mirrors A2UI catalog convention)

- **Layout:** Stack, Card (container), Form (container)
- **Display:** Text, Heading, Badge, KeyValue, Stat, Divider, Spacer, Image, Table, BarChart, LineChart, ProgressBar
- **Interactive:** Button, TextField, Select, Slider, Checkbox, Toggle

Abstract types only — the renderer owns the final visual implementation. The same blueprint could later render via Web Components, React, SwiftUI, or Flutter hosts; v0.1 ships exactly one renderer (vanilla HTML/CSS) to keep the surface sovereign and light.

## 9. Upgrade path (Path B — wrap in transport)

v0.1 is static: createSurface + updateComponents + updateDataModel baked into one blueprint, deleteSurface = close the tab. When the DSL is validated in the field:
- **Patch updates:** stream data model changes as RFC 6901 JSON Pointer patches bound to existing ids — regenerate only what changed, save token bandwidth (A2UI's core economy).
- **Transport:** AG-UI event protocol over SSE for live bidirectional streaming (A2UI-compatible day zero).
- **MCP endpoint:** expose the renderer factory as an MCP tool returning `ui://`-style URIs.
None of this changes the blueprint contract. That's the point of contract-first.

## 10. Rejected alternatives (and why)

- **Raw HTML/JS generation** — catastrophic security surface, strains hosts, hallucination magnet.
- **MCP Apps ui:// iframes** — code isolation is great, but remote-controlled styling means visual disjointedness from any host design system. Better for desktop chat apps than embedded copilots. We take its sandboxing lesson, not its model.
- **Vercel RSC / CopilotKit GraphQL / cloud SDKs** — vendor-locked, heavy, not sovereign.
- **Markdown-only** — no interactivity, no layout control. The bottleneck this skill exists to kill.
- **Unverified claims (Macaron, Bumblebee-as-declared)** — no receipts, no adoption.

This tracks the W3C WebAI consensus direction: constrained DSL, allowed elements only, mandatory sandboxing, dangerous attributes excluded by default, WCAG/ARIA inherited from the renderer, not the model.

## 11. Protocol positioning (AgentSurface in the stack)

| Attribute | Google A2UI | CopilotKit AG-UI | MCP Apps | **AgentSurface v0.1** |
|---|---|---|---|---|
| Core function | UI description (the "what") | Transport & state (the "how") | UI resource fetching | **The what + a sovereign renderer, zero transport** |
| Payload | Declarative JSON adjacency list | Event-based SSE streams | Pre-built HTML / sandboxed code | Declarative JSON adjacency list |
| Rendering | Client-side native (React, Flutter, Lit) | Agnostic (carries A2UI) | Sandboxed iframe (ui://) | Single vanilla HTML file, CSP-safe |
| Visual consistency | Matches host design system | N/A | Remote-controlled, disjointed | Self-contained; abstract types leave styling to the renderer |
| Primary use case | Cross-platform custom UI | Multi-agent backend sync | ChatGPT/Claude desktop ecosystems | **Any agent, any host, no backend** |

AgentSurface = A2UI's declarative primitive + MCP Apps' sandboxing discipline, minus every transport and vendor dependency. SDK ecosystems (Vercel AI SDK's streamUI/RSC tool-calling paradigms, CopilotKit's orchestration, Tambo, assistant-ui, Thesys) solve the *hosted-app* problem — they need a running app to embed in. AgentSurface solves the *every-agent* problem — the surface IS the app, for one moment, then it dissolves. Complementary, not competing: a validated AgentSurface DSL graduates into A2UI-streamed payloads via AG-UI transport in Path B.

## 12. Token economy (the Thesys lesson)

OpenUI Lang proves compact DSLs win on tokens and render speed. AgentSurface's economy rules: short stable ids (c1, f2, s1) reused across revisions; props omitted when default; flat lists stream incrementally; revisions keep unchanged ids so only deltas need describing. Never emit prose inside props — the surface frame (title/subtitle) is the only place for natural language.

## 13. Security architecture (the Lethal Trifecta, neutralized by design)

Generative UI's core threat: an agent emitting executable JS → UI injection → cookie exfiltration, fake modals, data dumps. AgentSurface kills the trifecta structurally:

- **Logic-agnostic surfaces.** The blueprint contains ZERO executable code (gate: no prop accepts a function, script, or handler string — there is no prop for it at all). The LLM arranges semantic controls; it cannot express execution.
- **Declarative Intent Bindings.** Buttons declare intent strings, not behavior. Renderer enforces `checkIntent()` — a button whose intent isn't in the blueprint's own whitelist throws and blocks (client-side firewall). A manipulated `DUMP_DATABASE` intent dies at the router.
- **textContent-only rendering.** No innerHTML for payload strings — markup injection is structurally impossible, not just filtered.
- **Zero network, zero eval, zero externals.** The renderer cannot exfiltrate anything: it makes no requests at all. The envelope is the only egress, and it's user-actioned, visible, and copied by hand.
- **Event Hydration.** The envelope (with ts) is the telemetry piped back into agent context — the agent stays aware of user progress without any open channel.

Supply chain (backend, out of scope for v0.1 but binding for Path B): MCP servers are a poorly monitored attack surface; scanners like Bumblebee (Perplexity, read-only, Go, zero-dep) or equivalents become mandatory CI gates before any MCP wrap ships. Verify any scanner's own provenance before adoption — no receipts, no dependency.

## 14. Compliance at the presentation layer (future gate)

Treat prompts AND model output as untrusted. Centralizing policy in the intent router + component catalog makes compliance deterministic even when the UI is dynamic: prop-level guardrails can strip PII (e.g. SSN → last-4), wrap sensitive components in session-timeout containers, and refuse components carrying disallowed data keys. v0.1 ships none of this — flagged as the first enterprise gate when a hosted variant exists.

## 15. Model horizon

Fine-tuned UI agents (reported: Macaron-A2UI family, LoRA + RL on A2UI-Bench) treat generative UI as a distinct ML problem — fewer syntax errors, more efficient form/slider/nav synthesis. AgentSurface's flat id-addressed DSL is exactly the training-shaped target such models optimize toward: short tokens, stable anchors, incremental deltas. When a proven fine-tuned UI model ships, it plugs into this contract unchanged.
