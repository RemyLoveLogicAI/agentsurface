#!/usr/bin/env python3
"""AgentSurface MCP server — zero-dependency stdio server exposing the
AgentSurface v0.1 DSL as native MCP tools.

Tools:
  validate_blueprint  — run the 8 gates from skill/references/dsl-spec.md §6
  scaffold_blueprint  — build a valid blueprint from a compact field spec
  render_surface      — inject a validated blueprint into the CSP-safe renderer

Transport: JSON-RPC 2.0 over newline-delimited stdin/stdout (MCP stdio).
Dependencies: none. Python 3.9+ standard library only.

Wiring (any MCP client):
  "mcpServers": {"agentsurface": {"command": "python3",
                                  "args": ["<repo>/mcp/server.py"]}}
"""

import json
import os
import sys
import tempfile
import time

SERVER_NAME = "agentsurface"
SERVER_VERSION = "0.1.0"
DEFAULT_PROTOCOL = "2025-06-18"
SUPPORTED_PROTOCOLS = ("2025-06-18", "2025-03-26", "2024-11-05")

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
TEMPLATE_PATH = os.environ.get(
    "AGENTSURFACE_TEMPLATE",
    os.path.join(REPO, "skill", "templates", "surface-template.html"),
)

# ---------------------------------------------------------------------------
# DSL contract (mirrors skill/scripts/validate_blueprint.py — single source of
# truth for the gate semantics, refactored to return errors instead of exiting)
# ---------------------------------------------------------------------------

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
TEXTUAL_PROPS = ("text", "label", "title", "subtitle", "placeholder", "alt")
INPUT_TYPES = {"TextField", "Select", "Slider", "Checkbox", "Toggle"}


class Rejected(Exception):
    """A blueprint failed a validation gate."""

    def __init__(self, gate, message):
        super().__init__("REJECTED [gate %d]: %s" % (gate, message))
        self.gate = gate
        self.message = message


def _gate1_parse(blueprint):
    """Gate 1 — JSON parses and the top-level shape is right."""
    if isinstance(blueprint, str):
        try:
            blueprint = json.loads(blueprint)
        except Exception as exc:
            raise Rejected(1, "JSON does not parse: %s" % exc)
    if not isinstance(blueprint, dict):
        raise Rejected(1, "blueprint must be a JSON object")
    comps = blueprint.get("components")
    if not isinstance(comps, list) or not comps:
        raise Rejected(1, "components must be a non-empty array")
    for i, comp in enumerate(comps):
        if not isinstance(comp, dict):
            raise Rejected(1, "components[%d] must be an object" % i)
        props = comp.get("props", {})
        if not isinstance(props, dict):
            raise Rejected(1, "components[%d].props must be an object" % i)
    if not isinstance(blueprint.get("dataModel", {}), dict):
        raise Rejected(1, "dataModel must be an object")
    if not isinstance(blueprint.get("intents", []), list):
        raise Rejected(1, "intents must be an array of strings")
    return blueprint


def _gate2_flat(comps):
    """Gate 2 — flat adjacency list; no component object nested in another."""

    def scan(obj, parent_key=""):
        if isinstance(obj, dict):
            if "type" in obj and "id" in obj and parent_key != "":
                raise Rejected(
                    2,
                    "nested component object under %s — adjacency list ONLY, "
                    "never nest" % parent_key,
                )
            for key, value in obj.items():
                scan(value, "%s.%s" % (parent_key, key))
        elif isinstance(obj, list):
            for i, value in enumerate(obj):
                scan(value, "%s[%d]" % (parent_key, i))

    for comp in comps:
        scan(comp, "")


def _gate3_graph(comps):
    """Gate 3 — unique ids, no orphans, no cycles, exactly one root."""
    ids = [c.get("id") for c in comps]
    if any(not i or not isinstance(i, str) for i in ids):
        raise Rejected(3, "every component needs a non-empty string id")
    if len(set(ids)) != len(ids):
        dupes = sorted({i for i in ids if ids.count(i) > 1})
        raise Rejected(3, "duplicate ids: %s" % dupes)

    by_id = {c["id"]: c for c in comps}
    child_of = {}
    for comp in comps:
        children = comp.get("children", [])
        if not isinstance(children, list):
            raise Rejected(3, "'%s' children must be an array of ids" % comp["id"])
        for child in children:
            if not isinstance(child, str):
                raise Rejected(
                    3, "'%s' children must be id strings, got %r" % (comp["id"], child)
                )
            if child not in by_id:
                raise Rejected(
                    3, "child '%s' referenced but not defined (orphan)" % child
                )
            if child in child_of:
                raise Rejected(3, "'%s' has two parents" % child)
            child_of[child] = comp["id"]
            seen, cur = set(), child
            while cur:
                if cur in seen:
                    raise Rejected(3, "cycle detected through '%s'" % cur)
                seen.add(cur)
                cur = child_of.get(cur)

    roots = [c["id"] for c in comps if c["id"] not in child_of]
    if len(roots) != 1:
        raise Rejected(
            3, "exactly one root required, found %d: %s" % (len(roots), roots)
        )
    return roots[0], by_id


def _gate4_types(comps):
    for comp in comps:
        if comp.get("type") not in TYPES:
            raise Rejected(
                4, "unknown type '%s' on '%s'" % (comp.get("type"), comp["id"])
            )


def _gate5_binds(comps, data_model):
    for comp in comps:
        bind = comp.get("props", {}).get("bind")
        if bind and bind not in data_model:
            raise Rejected(
                5, "bind '%s' on '%s' not present in dataModel" % (bind, comp["id"])
            )


def _gate6_intents(comps, intents):
    for comp in comps:
        action = comp.get("props", {}).get("action")
        if action is None:
            continue
        if not isinstance(action, dict) or "intent" not in action:
            raise Rejected(
                6, "Button '%s' action must be {intent, payloadKeys?}" % comp["id"]
            )
        if action["intent"] not in intents:
            raise Rejected(
                6,
                "intent '%s' on '%s' not in the intents whitelist"
                % (action["intent"], comp["id"]),
            )


def _gate7_props(comps):
    for comp in comps:
        extra = set(comp.get("props", {}).keys()) - ALLOWED_PROPS[comp["type"]]
        if extra:
            raise Rejected(
                7,
                "'%s' (%s) has undocumented props: %s — hallucination signature"
                % (comp["id"], comp["type"], sorted(extra)),
            )


def _gate8_text(comps):
    for comp in comps:
        for key, value in comp.get("props", {}).items():
            if key in TEXTUAL_PROPS and not isinstance(value, str):
                raise Rejected(
                    8, "'%s' prop '%s' must be a plain string" % (comp["id"], key)
                )


def validate(blueprint):
    """Run all 8 gates. Returns a summary dict, or raises Rejected."""
    blueprint = _gate1_parse(blueprint)
    comps = blueprint["components"]
    data_model = blueprint.get("dataModel", {})
    intents = blueprint.get("intents", [])

    _gate2_flat(comps)
    root, _ = _gate3_graph(comps)
    _gate4_types(comps)
    _gate5_binds(comps, data_model)
    _gate6_intents(comps, intents)
    _gate7_props(comps)
    _gate8_text(comps)

    binds = sorted(
        {
            c["props"]["bind"]
            for c in comps
            if c.get("props", {}).get("bind")
        }
    )
    fired = sorted(
        {
            c["props"]["action"]["intent"]
            for c in comps
            if isinstance(c.get("props", {}).get("action"), dict)
        }
    )
    return {
        "valid": True,
        "components": len(comps),
        "containers": sum(1 for c in comps if c["type"] in CONTAINERS),
        "root": root,
        "dataModelKeys": sorted(data_model.keys()),
        "binds": binds,
        "intents": list(intents),
        "firedIntents": fired,
        "unusedIntents": sorted(set(intents) - set(fired)),
        "summary": (
            "VALID — %d components (%d containers), root '%s', %d dataModel keys, "
            "%d whitelisted intents."
            % (
                len(comps),
                sum(1 for c in comps if c["type"] in CONTAINERS),
                root,
                len(data_model),
                len(intents),
            )
        ),
    }


# ---------------------------------------------------------------------------
# scaffold
# ---------------------------------------------------------------------------

_FIELD_DEFAULTS = {
    "TextField": "",
    "Select": None,      # first option
    "Slider": None,      # min
    "Checkbox": False,
    "Toggle": False,
}


def scaffold(spec):
    """Build a valid blueprint from a compact field spec.

    spec = {
      surface_id?, title, subtitle?, width?,
      intent, submit_label?, intro?,
      fields: [{type, label, bind, placeholder?, multiline?, required?,
                options?, min?, max?, step?, default?}]
    }
    """
    if not isinstance(spec, dict):
        raise Rejected(1, "scaffold spec must be an object")
    title = spec.get("title")
    intent = spec.get("intent")
    fields = spec.get("fields")
    if not isinstance(title, str) or not title.strip():
        raise Rejected(1, "scaffold requires a non-empty 'title' string")
    if not isinstance(intent, str) or not intent.strip():
        raise Rejected(1, "scaffold requires a non-empty 'intent' string")
    if not isinstance(fields, list) or not fields:
        raise Rejected(1, "scaffold requires a non-empty 'fields' array")

    surface_id = spec.get("surface_id") or "s1"
    width = spec.get("width", "compact")
    if width not in ("compact", "wide"):
        raise Rejected(1, "width must be 'compact' or 'wide'")

    components = []
    data_model = {}
    used_binds = []

    # Root: Stack > Card > Form
    components.append({"id": "c1", "type": "Stack",
                       "props": {"direction": "column", "gap": 16},
                       "children": ["c2"]})
    card_children = []
    components.append({"id": "c2", "type": "Card",
                       "props": {"tone": "default"}, "children": card_children})

    next_id = 3
    if spec.get("intro"):
        intro_id = "c%d" % next_id
        next_id += 1
        components.append({"id": intro_id, "type": "Text",
                           "props": {"text": str(spec["intro"]), "muted": True}})
        card_children.append(intro_id)

    form_children = []
    form_id = "c%d" % next_id
    next_id += 1
    components.append({"id": form_id, "type": "Form", "props": {},
                       "children": form_children})
    card_children.append(form_id)

    for i, field in enumerate(fields):
        if not isinstance(field, dict):
            raise Rejected(1, "fields[%d] must be an object" % i)
        ftype = field.get("type", "TextField")
        if ftype not in INPUT_TYPES:
            raise Rejected(
                4,
                "fields[%d] type '%s' is not an input type %s"
                % (i, ftype, sorted(INPUT_TYPES)),
            )
        bind = field.get("bind") or "f%d" % (i + 1)
        if bind in data_model:
            raise Rejected(3, "duplicate bind '%s' in fields" % bind)
        label = field.get("label") or bind
        if not isinstance(label, str):
            raise Rejected(8, "fields[%d] label must be a plain string" % i)

        props = {"label": label, "bind": bind}
        if ftype == "TextField":
            if field.get("placeholder"):
                props["placeholder"] = str(field["placeholder"])
            if field.get("multiline"):
                props["multiline"] = True
            if field.get("required"):
                props["required"] = True
            default = field.get("default", "")
        elif ftype == "Select":
            options = field.get("options")
            if not isinstance(options, list) or not options:
                raise Rejected(1, "fields[%d] Select needs a non-empty options array" % i)
            props["options"] = options
            first = options[0]
            first = first.get("value") if isinstance(first, dict) else first
            default = field.get("default", first)
        elif ftype == "Slider":
            lo = field.get("min", 0)
            hi = field.get("max", 100)
            props["min"] = lo
            props["max"] = hi
            props["step"] = field.get("step", 1)
            default = field.get("default", lo)
        else:  # Checkbox / Toggle
            default = field.get("default", False)

        comp_id = "f%d" % (i + 1)
        components.append({"id": comp_id, "type": ftype, "props": props})
        form_children.append(comp_id)
        data_model[bind] = default
        used_binds.append(bind)

    btn_id = "b1"
    components.append({
        "id": btn_id,
        "type": "Button",
        "props": {
            "label": spec.get("submit_label") or "Submit",
            "action": {"intent": intent, "payloadKeys": used_binds},
        },
    })
    form_children.append(btn_id)

    blueprint = {
        "surface": {"id": surface_id, "title": title, "width": width},
        "dataModel": data_model,
        "components": components,
        "intents": [intent],
    }
    if spec.get("subtitle"):
        blueprint["surface"]["subtitle"] = str(spec["subtitle"])

    validate(blueprint)  # never hand back a scaffold that fails its own gates
    return blueprint


# ---------------------------------------------------------------------------
# render
# ---------------------------------------------------------------------------

def _safe_json_for_script(obj):
    """Serialize for embedding inside a <script> block.

    ensure_ascii escapes all non-ASCII; then neutralize the characters that
    could break out of the script element or a JS string literal.
    """
    text = json.dumps(obj, ensure_ascii=True, separators=(",", ":"))
    return (
        text.replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
    )


def render(blueprint, output_path=None, template_path=None):
    """Validate, then inject the blueprint into the CSP-safe renderer."""
    summary = validate(blueprint)
    if isinstance(blueprint, str):
        blueprint = json.loads(blueprint)

    tpl_path = template_path or TEMPLATE_PATH
    if not os.path.isfile(tpl_path):
        raise Rejected(
            1,
            "renderer template not found at %s — set AGENTSURFACE_TEMPLATE or run "
            "the server from inside the agentsurface repo" % tpl_path,
        )
    with open(tpl_path, "r", encoding="utf-8") as fh:
        template = fh.read()
    if "__BLUEPRINT__" not in template:
        raise Rejected(1, "template %s has no __BLUEPRINT__ placeholder" % tpl_path)

    html = template.replace("__BLUEPRINT__", _safe_json_for_script(blueprint), 1)

    if output_path:
        path = os.path.abspath(os.path.expanduser(output_path))
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
    else:
        slug = str((blueprint.get("surface") or {}).get("id") or "surface")
        slug = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in slug)
        path = os.path.join(
            tempfile.gettempdir(), "surface-%s-%d.html" % (slug, int(time.time()))
        )
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(html)

    return {
        "path": path,
        "bytes": len(html.encode("utf-8")),
        "selfContained": ("<script src" not in html and "__BLUEPRINT__" not in html),
        "validation": summary,
    }


# ---------------------------------------------------------------------------
# MCP tool surface
# ---------------------------------------------------------------------------

_BLUEPRINT_SCHEMA = {
    "type": "object",
    "description": "An AgentSurface v0.1 blueprint (flat adjacency list).",
    "properties": {
        "surface": {"type": "object"},
        "dataModel": {"type": "object"},
        "components": {"type": "array", "items": {"type": "object"}},
        "intents": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["components"],
}

TOOLS = [
    {
        "name": "validate_blueprint",
        "title": "Validate AgentSurface blueprint",
        "description": (
            "Run the 8 AgentSurface DSL gates on a blueprint: JSON shape, flatness "
            "(no nested component trees), graph integrity (unique ids, one root, no "
            "orphans or cycles), type whitelist, bind resolution against dataModel, "
            "intent-firewall whitelist, undocumented-prop rejection, and plain-string "
            "text props. Returns a pass summary or the exact gate that rejected it. "
            "Always call this before render_surface."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"blueprint": _BLUEPRINT_SCHEMA},
            "required": ["blueprint"],
            "additionalProperties": False,
        },
    },
    {
        "name": "scaffold_blueprint",
        "title": "Scaffold AgentSurface blueprint",
        "description": (
            "Build a guaranteed-valid blueprint (Stack > Card > Form + submit Button) "
            "from a compact field spec, so the model never hand-writes the adjacency "
            "list. Every field becomes a bound input with a dataModel entry, and the "
            "submit Button's intent is added to the whitelist. Output is validated "
            "before it is returned."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Surface title."},
                "subtitle": {"type": "string"},
                "intro": {"type": "string", "description": "Optional muted intro Text."},
                "surface_id": {"type": "string", "default": "s1"},
                "width": {"type": "string", "enum": ["compact", "wide"]},
                "intent": {
                    "type": "string",
                    "description": "Intent string the submit Button fires, e.g. submit_scope.",
                },
                "submit_label": {"type": "string", "default": "Submit"},
                "fields": {
                    "type": "array",
                    "minItems": 1,
                    "description": "Inputs, in order.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "type": {
                                "type": "string",
                                "enum": sorted(INPUT_TYPES),
                                "default": "TextField",
                            },
                            "label": {"type": "string"},
                            "bind": {
                                "type": "string",
                                "description": "dataModel key; defaults to f1, f2, ...",
                            },
                            "placeholder": {"type": "string"},
                            "multiline": {"type": "boolean"},
                            "required": {"type": "boolean"},
                            "options": {
                                "type": "array",
                                "description": "Select options: strings or {label,value}.",
                            },
                            "min": {"type": "number"},
                            "max": {"type": "number"},
                            "step": {"type": "number"},
                            "default": {"description": "Initial dataModel value."},
                        },
                        "required": ["label"],
                    },
                },
            },
            "required": ["title", "intent", "fields"],
            "additionalProperties": False,
        },
    },
    {
        "name": "render_surface",
        "title": "Render AgentSurface surface",
        "description": (
            "Validate a blueprint, then inject it into the self-contained CSP-safe "
            "HTML renderer and write the file. Zero external scripts, zero network "
            "calls, zero eval; blueprint JSON is escaped so it cannot break out of "
            "the script element. Returns the output path and byte size. Rejects any "
            "blueprint that fails validation."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "blueprint": _BLUEPRINT_SCHEMA,
                "output_path": {
                    "type": "string",
                    "description": "Where to write the HTML. Defaults to a temp file.",
                },
                "template_path": {
                    "type": "string",
                    "description": "Override the renderer template path.",
                },
            },
            "required": ["blueprint"],
            "additionalProperties": False,
        },
    },
]


def _call_tool(name, args):
    if name == "validate_blueprint":
        return validate(args["blueprint"])
    if name == "scaffold_blueprint":
        spec = dict(args)
        return {"blueprint": scaffold(spec)}
    if name == "render_surface":
        return render(
            args["blueprint"],
            args.get("output_path"),
            args.get("template_path"),
        )
    raise KeyError(name)


# ---------------------------------------------------------------------------
# JSON-RPC plumbing
# ---------------------------------------------------------------------------

def _result(request_id, payload):
    return {"jsonrpc": "2.0", "id": request_id, "result": payload}


def _error(request_id, code, message):
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {"code": code, "message": message},
    }


def _text_content(payload):
    return {
        "content": [{"type": "text", "text": json.dumps(payload, indent=2)}],
        "structuredContent": payload,
        "isError": False,
    }


def _text_error(message):
    return {"content": [{"type": "text", "text": message}], "isError": True}


def handle(message):
    """Handle one JSON-RPC message. Returns a response dict, or None."""
    if not isinstance(message, dict):
        return _error(None, -32600, "Invalid Request: not an object")

    method = message.get("method")
    request_id = message.get("id")
    params = message.get("params") or {}
    is_notification = "id" not in message

    if method is None:
        return None if is_notification else _error(request_id, -32600, "Invalid Request")

    if method == "initialize":
        requested = params.get("protocolVersion")
        version = requested if requested in SUPPORTED_PROTOCOLS else DEFAULT_PROTOCOL
        return _result(request_id, {
            "protocolVersion": version,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
            "instructions": (
                "AgentSurface: emit a flat declarative blueprint instead of a wall of "
                "markdown. scaffold_blueprint to compose, validate_blueprint to gate, "
                "render_surface to produce the self-contained HTML surface. The user "
                "acts, the renderer emits an intent envelope, you ingest it."
            ),
        })

    if method in ("notifications/initialized", "initialized", "notifications/cancelled"):
        return None

    if method == "ping":
        return _result(request_id, {})

    if method == "tools/list":
        return _result(request_id, {"tools": TOOLS})

    if method == "tools/call":
        name = params.get("name")
        args = params.get("arguments") or {}
        if not isinstance(args, dict):
            return _result(request_id, _text_error("arguments must be an object"))
        try:
            return _result(request_id, _text_content(_call_tool(name, args)))
        except Rejected as exc:
            return _result(request_id, _text_error(str(exc)))
        except KeyError as exc:
            return _error(request_id, -32601, "Unknown tool: %s" % exc)
        except Exception as exc:  # never take the loop down over one bad call
            return _result(
                request_id, _text_error("%s: %s" % (type(exc).__name__, exc))
            )

    if is_notification:
        return None
    return _error(request_id, -32601, "Method not found: %s" % method)


def main():
    out = sys.stdout
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except Exception as exc:
            response = _error(None, -32700, "Parse error: %s" % exc)
        else:
            if isinstance(message, list):  # batch
                responses = [r for r in (handle(m) for m in message) if r is not None]
                for response in responses:
                    out.write(json.dumps(response) + "\n")
                out.flush()
                continue
            response = handle(message)
        if response is not None:
            out.write(json.dumps(response) + "\n")
            out.flush()


if __name__ == "__main__":
    main()
