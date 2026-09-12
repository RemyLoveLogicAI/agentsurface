#!/usr/bin/env python3
"""AgentSurface MCP Server — Path B.

Zero-dependency stdio MCP server (JSON-RPC 2.0, newline-delimited) exposing the
AgentSurface blueprint contract as native tools, so any MCP-compatible agent
(Claude instances, OpenClaw gateways, Mac mini agents) can compose, validate,
and render UI surfaces without changing their core loop.

Tools:
  validate_blueprint  — run the 8 gates (mirrors scripts/validate_blueprint.py)
  scaffold_blueprint  — deterministic starter blueprints by kind (dashboard, form, taskboard, comparison)
  render_surface      — validate + inject into the CSP-safe renderer template, return the HTML

Core rules enforced:
  - Data, not code. No executable JS in payloads.
  - Flat adjacency list only — nested trees rejected at gate 2.
  - Intent firewall — actions must be whitelisted at blueprint time.
  - Zero tolerance — invalid blueprints return isError so the calling agent can self-correct.

Run:  python3 server.py [--template path/to/surface-template.html]
Wire: add to any MCP client config as a stdio server:
      {"mcpServers": {"agentsurface": {"command": "python3", "args": ["<repo>/mcp/server.py"]}}}

NOTE: gate logic mirrors scripts/validate_blueprint.py — keep both in sync.
"""
import json, os, sys

from leaf_layer import inject_leaf

# ---------------------------------------------------------------- 8 gates ---
ALLOWED_PROPS = {
    "Stack": {"direction", "gap"},
    "Card": {"padding", "tone"},
    "Form": set(),
    "Text": {"text", "muted"},
    "Heading": {"text", "level"},
    "Badge": {"text", "tone"},
    "KeyValue": {"label", "value"},
    "Stat": {"label", "value", "unit"},
    "Divider": set(),
    "Spacer": {"size"},
    "Image": {"src", "alt"},
    "Table": {"columns", "rows", "dense"},
    "BarChart": {"title", "series", "unit"},
    "LineChart": {"title", "points", "labels"},
    "ProgressBar": {"value", "max", "label"},
    "TextField": {"label", "placeholder", "bind", "required", "multiline", "value"},
    "Select": {"label", "options", "bind", "value"},
    "Slider": {"label", "min", "max", "step", "bind", "value"},
    "Checkbox": {"label", "bind", "value"},
    "Toggle": {"label", "bind", "value"},
    "Button": {"label", "action"},
}
CONTAINERS = {"Stack", "Card", "Form"}
TYPES = set(ALLOWED_PROPS)


class GateError(Exception):
    def __init__(self, gate, msg):
        super().__init__(msg)
        self.gate = gate
        self.msg = msg


def _fail(gate, msg):
    raise GateError(gate, msg)


def validate(bp):
    """Runs the 8 gates. Returns (ok: bool, report: str)."""
    try:
        if not isinstance(bp, dict):
            _fail(1, "blueprint must be a JSON object")
        comps = bp.get("components")
        if not isinstance(comps, list) or not comps:
            _fail(1, "components must be a non-empty array")

        # Gate 2: flat — no component object nested inside another
        def scan_flat(obj, parent_key=""):
            if isinstance(obj, dict):
                if "type" in obj and "id" in obj and parent_key != "":
                    _fail(2, f"nested component object under {parent_key} — adjacency list ONLY, never nest")
                for k, v in obj.items():
                    scan_flat(v, f"{parent_key}.{k}")
            elif isinstance(obj, list):
                for i, v in enumerate(obj):
                    scan_flat(v, f"{parent_key}[{i}]")
        for c in comps:
            scan_flat(c, "")

        # Gate 3: ids unique, no orphans, no cycles, exactly one root
        ids = [c.get("id") for c in comps]
        if any(not i or not isinstance(i, str) for i in ids):
            _fail(3, "every component needs a non-empty string id")
        if len(set(ids)) != len(ids):
            dupes = [i for i in ids if ids.count(i) > 1]
            _fail(3, f"duplicate ids: {sorted(set(dupes))}")
        by_id = {c["id"]: c for c in comps}
        child_of = {}
        for c in comps:
            for ch in c.get("children", []):
                if ch not in by_id:
                    _fail(3, f"child '{ch}' referenced but not defined (orphan)")
                if ch in child_of:
                    _fail(3, f"'{ch}' has two parents")
                child_of[ch] = c["id"]
                seen, cur = set(), ch
                while cur:
                    if cur in seen:
                        _fail(3, f"cycle detected through '{cur}'")
                    seen.add(cur)
                    cur = child_of.get(cur)
        roots = [c["id"] for c in comps if c["id"] not in child_of]
        if len(roots) != 1:
            _fail(3, f"exactly one root required, found {len(roots)}: {roots}")

        # Gate 4: types whitelisted
        for c in comps:
            if c.get("type") not in TYPES:
                _fail(4, f"unknown type '{c.get('type')}' on '{c['id']}'")

        # Gate 5: binds exist in dataModel
        dm = bp.get("dataModel", {})
        if not isinstance(dm, dict):
            _fail(1, "dataModel must be an object")
        for c in comps:
            b = c.get("props", {}).get("bind")
            if b and b not in dm:
                _fail(5, f"bind '{b}' on '{c['id']}' not present in dataModel")

        # Gate 6: button intents whitelisted
        intents = bp.get("intents", [])
        if not isinstance(intents, list):
            _fail(1, "intents must be an array of strings")
        for c in comps:
            a = c.get("props", {}).get("action")
            if a is not None:
                if not isinstance(a, dict) or "intent" not in a:
                    _fail(6, f"Button '{c['id']}' action must be {{intent, payloadKeys?}}")
                if a["intent"] not in intents:
                    _fail(6, f"intent '{a['intent']}' on '{c['id']}' not in the intents whitelist")

        # Gate 7: no props outside the documented set
        for c in comps:
            allowed = ALLOWED_PROPS[c["type"]]
            extra = set(c.get("props", {}).keys()) - allowed
            if extra:
                _fail(7, f"'{c['id']}' ({c['type']}) has undocumented props: {sorted(extra)} — hallucination signature")

        # Gate 8: text props are plain strings
        for c in comps:
            for k, v in c.get("props", {}).items():
                if k in ("text", "label", "title", "subtitle", "placeholder", "alt") and not isinstance(v, str):
                    _fail(8, f"'{c['id']}' prop '{k}' must be a plain string")

        n_cont = sum(1 for c in comps if c["type"] in CONTAINERS)
        return True, (f"VALID — {len(comps)} components ({n_cont} containers), root '{roots[0]}', "
                      f"{len(dm)} dataModel keys, {len(intents)} whitelisted intents.")
    except GateError as g:
        return False, f"REJECTED [gate {g.gate}]: {g.msg}"


# -------------------------------------------------------------- scaffolds ---
def scaffold(kind, title, data):
    """Deterministic starter blueprints. Every scaffold passes the 8 gates."""
    kind = (kind or "").lower()

    if kind == "dashboard":
        stats = data.get("stats", [])
        kv = data.get("kv", [])
        comps = [{"id": "root", "type": "Stack", "props": {"direction": "column", "gap": "16"}}]
        if title:
            comps.append({"id": "title", "type": "Heading", "props": {"text": str(title), "level": 2}})
        if stats:
            sids = []
            for i, s in enumerate(stats):
                cid = f"stat{i}"
                comps.append({"id": cid, "type": "Stat", "props": {
                    "label": str(s.get("label", "")), "value": s.get("value", ""),
                    "unit": str(s.get("unit", ""))}})
                sids.append(cid)
            srow = {"id": "stats", "type": "Stack", "props": {"direction": "row", "gap": "12"}, "children": sids}
            comps.append(srow)
            comps[0]["children"] = comps[0].get("children", []) + ["title" if title else None, "stats"]
            comps[0]["children"] = [c for c in comps[0]["children"] if c]
        if kv:
            kcard = {"id": "kvcard", "type": "Card", "props": {"padding": "16"}, "children": []}
            for i, k in enumerate(kv):
                cid = f"kv{i}"
                comps.append({"id": cid, "type": "KeyValue", "props": {
                    "label": str(k.get("label", "")), "value": str(k.get("value", ""))}})
                kcard["children"].append(cid)
            comps.append(kcard)
            comps[0]["children"] = comps[0].get("children", []) + ["kvcard"]
        if len(comps) == 1:
            comps.append({"id": "empty", "type": "Text", "props": {"text": "No data provided.", "muted": True}})
            comps[0]["children"] = ["empty"]
        return {"components": comps, "dataModel": {}, "intents": []}

    if kind == "form":
        fields = data.get("fields", [])
        comps = [{"id": "root", "type": "Form", "props": {}, "children": []}]
        if title:
            comps.append({"id": "title", "type": "Heading", "props": {"text": str(title), "level": 2}})
            comps[0]["children"].append("title")
        dm, binds = {}, []
        for i, f in enumerate(fields):
            fid = f"field{i}"
            bind = str(f.get("bind") or f"field{i}")
            dm[bind] = f.get("value", "")
            binds.append(bind)
            ftype = str(f.get("kind", "text")).lower()
            if ftype == "select":
                comps.append({"id": fid, "type": "Select", "props": {
                    "label": str(f.get("label", bind)), "options": [str(o) for o in f.get("options", [])], "bind": bind}})
            elif ftype == "checkbox":
                comps.append({"id": fid, "type": "Checkbox", "props": {"label": str(f.get("label", bind)), "bind": bind}})
            elif ftype == "slider":
                comps.append({"id": fid, "type": "Slider", "props": {
                    "label": str(f.get("label", bind)), "min": f.get("min", 0), "max": f.get("max", 100),
                    "step": f.get("step", 1), "bind": bind}})
            else:
                comps.append({"id": fid, "type": "TextField", "props": {
                    "label": str(f.get("label", bind)), "placeholder": str(f.get("placeholder", "")),
                    "required": bool(f.get("required", False)), "bind": bind}})
            comps[0]["children"].append(fid)
        comps.append({"id": "submit", "type": "Button", "props": {
            "label": "Submit", "action": {"intent": "submit", "payloadKeys": binds}}})
        comps[0]["children"].append("submit")
        return {"components": comps, "dataModel": dm, "intents": ["submit"]}

    if kind == "taskboard":
        rows = [[str(t.get("task", "")), str(t.get("status", "")), str(t.get("owner", ""))]
                for t in data.get("tasks", [])]
        return {"components": [
            {"id": "root", "type": "Card", "props": {"padding": "16"}, "children": [
                *(["title"] if title else []), "table"]},
            *([{"id": "title", "type": "Heading", "props": {"text": str(title), "level": 2}}] if title else []),
            {"id": "table", "type": "Table", "props": {
                "columns": ["Task", "Status", "Owner"], "rows": rows, "dense": True}},
        ], "dataModel": {}, "intents": []}

    if kind == "comparison":
        return {"components": [
            {"id": "root", "type": "Card", "props": {"padding": "16"}, "children": [
                *(["title"] if title else []), "table"]},
            *([{"id": "title", "type": "Heading", "props": {"text": str(title), "level": 2}}] if title else []),
            {"id": "table", "type": "Table", "props": {
                "columns": [str(c) for c in data.get("columns", [])],
                "rows": [[str(v) for v in r] for r in data.get("rows", [])], "dense": True}},
        ], "dataModel": {}, "intents": []}

    raise GateError(1, f"unknown kind '{kind}' — use dashboard, form, taskboard, or comparison")


# ---------------------------------------------------------------- render ---
def render(bp, template_path):
    ok, report = validate(bp)
    if not ok:
        raise GateError(0, report)
    with open(template_path, encoding="utf-8") as f:
        template = f.read()
    if "__BLUEPRINT__" not in template:
        raise GateError(0, "template is missing the __BLUEPRINT__ injection marker")
    injected = json.dumps(bp).replace("</", "<\\/")
    return template.replace("__BLUEPRINT__", injected), report


# ------------------------------------------------------------------- MCP ---
TOOLS = [
    {
        "name": "validate_blueprint",
        "description": "Validate an AgentSurface JSON blueprint against the 8 gates "
                       "(parse, flat adjacency, graph integrity, type whitelist, bind integrity, "
                       "intent firewall, prop whitelist, plain strings). Returns VALID or the rejecting gate.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "blueprint": {
                    "type": ["object", "string"],
                    "description": "The blueprint as a JSON object, or a JSON string of it."}},
            "required": ["blueprint"]},
    },
    {
        "name": "scaffold_blueprint",
        "description": "Generate a deterministic starter blueprint that is guaranteed to pass validation. "
                       "kinds: dashboard (stats + key-values), form (fields + submit intent), "
                       "taskboard (task table), comparison (arbitrary table).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "kind": {"type": "string", "enum": ["dashboard", "form", "taskboard", "comparison"]},
                "title": {"type": "string"},
                "data": {
                    "type": "object",
                    "description": "dashboard: {stats:[{label,value,unit}], kv:[{label,value}]} · "
                                   "form: {fields:[{kind,label,bind,options?,required?}]} · "
                                   "taskboard: {tasks:[{task,status,owner}]} · comparison: {columns,rows}"}},
            "required": ["kind"]},
    },
    {
        "name": "render_surface",
        "description": "Validate the blueprint, then inject it into the CSP-safe AgentSurface renderer "
                       "and return the complete self-contained HTML file. Set leaf=true to add the leaf layer: "
                       "anchored comments pinned to component ids, emitted as a structured envelope "
                       "(type: leaf_feedback) the user pastes back to the agent. Save as surface-<slug>.html, "
                       "host anywhere (GitHub Pages, any static host), share the URL.",
        "inputSchema": {
            "type": "object",
            "properties": {"blueprint": {"type": ["object", "string"]},
                           "leaf": {"type": "boolean", "description": "enable anchored leaf comments"}},
            "required": ["blueprint"]},
    },
]

PROTOCOL_VERSION = "2024-11-05"


def call_tool(name, args):
    if name == "validate_blueprint":
        bp = args.get("blueprint")
        if isinstance(bp, str):
            try:
                bp = json.loads(bp)
            except Exception as e:
                return {"isError": True, "content": [{"type": "text", "text": f"REJECTED [gate 1]: JSON string does not parse: {e}"}]}
        ok, report = validate(bp)
        return {"isError": not ok, "content": [{"type": "text", "text": report}]}

    if name == "scaffold_blueprint":
        try:
            bp = scaffold(args.get("kind"), args.get("title", ""), args.get("data", {}))
            ok, report = validate(bp)
            return {"isError": not ok, "content": [{"type": "text",
                    "text": json.dumps({"blueprint": bp, "validation": report}, indent=2)}]}
        except GateError as g:
            return {"isError": True, "content": [{"type": "text", "text": g.msg}]}

    if name == "render_surface":
        bp = args.get("blueprint")
        if isinstance(bp, str):
            try:
                bp = json.loads(bp)
            except Exception as e:
                return {"isError": True, "content": [{"type": "text", "text": f"REJECTED [gate 1]: JSON string does not parse: {e}"}]}
        try:
            html, report = render(bp, TEMPLATE_PATH)
        except GateError as g:
            return {"isError": True, "content": [{"type": "text", "text": g.msg}]}
        if args.get("leaf"):
            html = inject_leaf(html)
            report = report + " Leaf layer injected: anchored comments on by component id."
        return {"isError": False, "content": [
            {"type": "text", "text": report},
            {"type": "text", "text": "Complete HTML below. Save as surface-<slug>.html and host as a static file."},
            {"type": "text", "text": html}]}

    return {"isError": True, "content": [{"type": "text", "text": f"unknown tool '{name}'"}]}


def handle(msg):
    method = msg.get("method")
    mid = msg.get("id")
    if method == "initialize":
        return {"jsonrpc": "2.0", "id": mid, "result": {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": "agentsurface", "version": "0.1.0"}}}
    if method == "ping":
        return {"jsonrpc": "2.0", "id": mid, "result": {}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": mid, "result": {"tools": TOOLS}}
    if method == "tools/call":
        params = msg.get("params", {})
        try:
            result = call_tool(params.get("name"), params.get("arguments") or {})
        except Exception as e:
            result = {"isError": True, "content": [{"type": "text", "text": f"tool error: {e}"}]}
        return {"jsonrpc": "2.0", "id": mid, "result": result}
    if mid is not None:
        return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"method not found: {method}"}}
    return None  # notification — ignore


def main():
    global TEMPLATE_PATH
    args = sys.argv[1:]
    script_dir = os.path.dirname(os.path.abspath(__file__))
    TEMPLATE_PATH = os.environ.get("AGENTSURFACE_TEMPLATE")
    if "--template" in args:
        TEMPLATE_PATH = args[args.index("--template") + 1]
    if not TEMPLATE_PATH:
        for cand in (os.path.join(script_dir, "..", "templates", "surface-template.html"),
                     os.path.join(script_dir, "templates", "surface-template.html")):
            if os.path.exists(cand):
                TEMPLATE_PATH = os.path.abspath(cand)
                break
    if "--print-template" in args:
        print(TEMPLATE_PATH or "(not found)")
        return
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except Exception:
            continue
        resp = handle(msg)
        if resp is not None:
            sys.stdout.write(json.dumps(resp) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
