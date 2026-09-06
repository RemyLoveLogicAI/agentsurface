#!/usr/bin/env python3
"""AgentSurface blueprint validator — the 8 gates from references/dsl-spec.md §6.
Usage: python3 validate_blueprint.py blueprint.json
Exit 0 = valid. Exit 1 = rejected, with the gate that failed."""
import json, sys

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

def fail(gate, msg):
    print(f"REJECTED [gate {gate}]: {msg}")
    sys.exit(1)

def main(path):
    # Gate 1: parses
    try:
        bp = json.load(open(path))
    except Exception as e:
        fail(1, f"JSON does not parse: {e}")

    comps = bp.get("components")
    if not isinstance(comps, list) or not comps:
        fail(1, "components must be a non-empty array")

    # Gate 2: flat — no component object nested inside another
    def scan_flat(obj, parent_key=""):
        if isinstance(obj, dict):
            if "type" in obj and "id" in obj and parent_key != "":
                fail(2, f"nested component object under {parent_key} — adjacency list ONLY, never nest")
            for k, v in obj.items():
                scan_flat(v, f"{parent_key}.{k}")
        elif isinstance(obj, list):
            for i, v in enumerate(obj):
                scan_flat(v, f"{parent_key}[{i}]")
    for i, c in enumerate(comps):
        scan_flat(c, "")  # top level: parent key empty, only true nesting fails

    # Gate 3: ids unique, no orphans, no cycles, exactly one root
    ids = [c.get("id") for c in comps]
    if any(not i or not isinstance(i, str) for i in ids):
        fail(3, "every component needs a non-empty string id")
    if len(set(ids)) != len(ids):
        dupes = [i for i in ids if ids.count(i) > 1]
        fail(3, f"duplicate ids: {sorted(set(dupes))}")
    by_id = {c["id"]: c for c in comps}
    child_of = {}
    for c in comps:
        for ch in c.get("children", []):
            if ch not in by_id:
                fail(3, f"child '{ch}' referenced but not defined (orphan)")
            if ch in child_of:
                fail(3, f"'{ch}' has two parents")
            child_of[ch] = c["id"]
            # cycle check via walk
            seen, cur = set(), ch
            while cur:
                if cur in seen:
                    fail(3, f"cycle detected through '{cur}'")
                seen.add(cur)
                cur = child_of.get(cur)
    roots = [c["id"] for c in comps if c["id"] not in child_of]
    if len(roots) != 1:
        fail(3, f"exactly one root required, found {len(roots)}: {roots}")

    # Gate 4: types whitelisted
    for c in comps:
        if c.get("type") not in TYPES:
            fail(4, f"unknown type '{c.get('type')}' on '{c['id']}'")

    # Gate 5: binds exist in dataModel
    dm = bp.get("dataModel", {})
    if not isinstance(dm, dict):
        fail(1, "dataModel must be an object")
    for c in comps:
        b = c.get("props", {}).get("bind")
        if b and b not in dm:
            fail(5, f"bind '{b}' on '{c['id']}' not present in dataModel")

    # Gate 6: button intents whitelisted
    intents = bp.get("intents", [])
    if not isinstance(intents, list):
        fail(1, "intents must be an array of strings")
    for c in comps:
        a = c.get("props", {}).get("action")
        if a is not None:
            if not isinstance(a, dict) or "intent" not in a:
                fail(6, f"Button '{c['id']}' action must be {{intent, payloadKeys?}}")
            if a["intent"] not in intents:
                fail(6, f"intent '{a['intent']}' on '{c['id']}' not in the intents whitelist")

    # Gate 7: no props outside the documented set
    for c in comps:
        allowed = ALLOWED_PROPS[c["type"]]
        extra = set(c.get("props", {}).keys()) - allowed
        if extra:
            fail(7, f"'{c['id']}' ({c['type']}) has undocumented props: {sorted(extra)} — hallucination signature")

    # Gate 8: text props are plain strings (renderer uses textContent; check inputs anyway)
    for c in comps:
        for k, v in c.get("props", {}).items():
            if k in ("text", "label", "title", "subtitle", "placeholder", "alt") and not isinstance(v, str):
                fail(8, f"'{c['id']}' prop '{k}' must be a plain string")

    n_cont = sum(1 for c in comps if c["type"] in CONTAINERS)
    print(f"VALID — {len(comps)} components ({n_cont} containers), root '{roots[0]}', "
          f"{len(dm)} dataModel keys, {len(intents)} whitelisted intents.")
    sys.exit(0)

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("usage: validate_blueprint.py blueprint.json")
        sys.exit(1)
    main(sys.argv[1])
