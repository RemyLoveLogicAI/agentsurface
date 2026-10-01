#!/usr/bin/env python3
"""Live test harness for the AgentSurface MCP server.

Spawns mcp/server.py as a real subprocess and speaks JSON-RPC over stdio —
no mocking, no dependencies. Exercises the handshake, the tool inventory, the
happy path, the hallucination rejections, and a full render.

Usage: python3 mcp/test_mcp.py        (exit 0 = all green)
"""

import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SERVER = os.path.join(HERE, "server.py")

PASS, FAIL = [], []


def check(name, condition, detail=""):
    if condition:
        PASS.append(name)
        print("  PASS  %s" % name)
    else:
        FAIL.append((name, detail))
        print("  FAIL  %s%s" % (name, ("  -> " + str(detail)) if detail else ""))
    return bool(condition)


class Server:
    """One server subprocess, one JSON-RPC session."""

    def __init__(self):
        self.proc = subprocess.Popen(
            [sys.executable, SERVER],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        self._id = 0

    def request(self, method, params=None):
        self._id += 1
        msg = {"jsonrpc": "2.0", "id": self._id, "method": method}
        if params is not None:
            msg["params"] = params
        self.proc.stdin.write(json.dumps(msg) + "\n")
        self.proc.stdin.flush()
        line = self.proc.stdout.readline()
        if not line:
            err = self.proc.stderr.read()
            raise RuntimeError("server closed stdout. stderr:\n%s" % err)
        return json.loads(line)

    def notify(self, method, params=None):
        msg = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            msg["params"] = params
        self.proc.stdin.write(json.dumps(msg) + "\n")
        self.proc.stdin.flush()

    def call(self, tool, arguments):
        return self.request("tools/call", {"name": tool, "arguments": arguments})

    def close(self):
        try:
            self.proc.stdin.close()
            self.proc.wait(timeout=5)
        except Exception:
            self.proc.kill()


def structured(response):
    """Pull the structured payload out of a tools/call result."""
    result = response.get("result", {})
    if result.get("isError"):
        return None, result["content"][0]["text"]
    return result.get("structuredContent"), None


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------

VALID_BLUEPRINT = {
    "surface": {"id": "s1", "title": "Deploy check", "subtitle": "One moment",
                "width": "compact"},
    "dataModel": {"env": "staging", "confirm": False, "note": ""},
    "components": [
        {"id": "c1", "type": "Stack", "props": {"direction": "column", "gap": 16},
         "children": ["c2", "c5"]},
        {"id": "c2", "type": "Card", "props": {"tone": "accent"},
         "children": ["c3", "c4"]},
        {"id": "c3", "type": "Heading", "props": {"text": "Target", "level": 2}},
        {"id": "c4", "type": "Stat", "props": {"label": "Pending", "value": "3",
                                               "unit": "jobs"}},
        {"id": "c5", "type": "Form", "props": {},
         "children": ["f1", "f2", "f3", "b1"]},
        {"id": "f1", "type": "Select", "props": {"label": "Environment",
                                                 "options": ["staging", "prod"],
                                                 "bind": "env"}},
        {"id": "f2", "type": "Toggle", "props": {"label": "I confirm",
                                                 "bind": "confirm"}},
        {"id": "f3", "type": "TextField", "props": {"label": "Note",
                                                    "placeholder": "optional",
                                                    "bind": "note"}},
        {"id": "b1", "type": "Button",
         "props": {"label": "Deploy",
                   "action": {"intent": "submit_deploy",
                              "payloadKeys": ["env", "confirm", "note"]}}},
    ],
    "intents": ["submit_deploy"],
}

# gate 2 — the nested-tree hallucination, the failure mode the DSL exists to kill
NESTED_BLUEPRINT = {
    "surface": {"id": "s2", "title": "Nested"},
    "dataModel": {},
    "components": [
        {"id": "c1", "type": "Card", "props": {}, "children": [
            {"id": "c2", "type": "Text", "props": {"text": "I am nested"}}
        ]},
    ],
    "intents": [],
}

# gate 6 — an intent that was never whitelisted
ROGUE_INTENT_BLUEPRINT = {
    "surface": {"id": "s3", "title": "Rogue"},
    "dataModel": {},
    "components": [
        {"id": "c1", "type": "Form", "props": {}, "children": ["b1"]},
        {"id": "b1", "type": "Button",
         "props": {"label": "Go", "action": {"intent": "DUMP_DATABASE"}}},
    ],
    "intents": ["submit_scope"],
}

# gate 5 — a bind with no dataModel entry
UNBOUND_BLUEPRINT = {
    "surface": {"id": "s4", "title": "Unbound"},
    "dataModel": {"other": ""},
    "components": [
        {"id": "c1", "type": "Form", "props": {}, "children": ["f1"]},
        {"id": "f1", "type": "TextField", "props": {"label": "Name", "bind": "name"}},
    ],
    "intents": [],
}

# gate 7 — invented prop, the hallucination signature
BAD_PROP_BLUEPRINT = {
    "surface": {"id": "s5", "title": "Bad prop"},
    "dataModel": {},
    "components": [
        {"id": "c1", "type": "Text", "props": {"text": "hi", "onClick": "alert(1)"}},
    ],
    "intents": [],
}

# gate 3 — two roots
TWO_ROOT_BLUEPRINT = {
    "surface": {"id": "s6", "title": "Two roots"},
    "dataModel": {},
    "components": [
        {"id": "c1", "type": "Text", "props": {"text": "a"}},
        {"id": "c2", "type": "Text", "props": {"text": "b"}},
    ],
    "intents": [],
}

AUDIT_SCAFFOLD_SPEC = {
    "title": "Audit intake",
    "subtitle": "Scope the engagement",
    "intro": "Pick the scope and submit — I'll take it from here.",
    "intent": "submit_audit_scope",
    "submit_label": "Start audit",
    "width": "compact",
    "fields": [
        {"type": "TextField", "label": "Repository", "bind": "repo",
         "placeholder": "owner/name", "required": True},
        {"type": "Select", "label": "Depth", "bind": "depth",
         "options": ["surface", "standard", "deep"], "default": "standard"},
        {"type": "Slider", "label": "Max files", "bind": "max_files",
         "min": 10, "max": 500, "step": 10, "default": 100},
        {"type": "Checkbox", "label": "Include dependencies", "bind": "deps"},
        {"type": "TextField", "label": "Notes", "bind": "notes", "multiline": True},
    ],
}


# ---------------------------------------------------------------------------
# tests
# ---------------------------------------------------------------------------

def main():
    srv = Server()
    try:
        print("\n[1] handshake")
        resp = srv.request("initialize", {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "test_mcp", "version": "0"},
        })
        init = resp.get("result", {})
        check("initialize returns serverInfo",
              init.get("serverInfo", {}).get("name") == "agentsurface", init)
        check("protocol version negotiated",
              init.get("protocolVersion") == "2025-06-18", init.get("protocolVersion"))
        check("declares tools capability", "tools" in init.get("capabilities", {}), init)
        srv.notify("notifications/initialized")
        check("ping answers", srv.request("ping").get("result") == {})

        print("\n[2] tool inventory")
        tools = srv.request("tools/list").get("result", {}).get("tools", [])
        names = sorted(t["name"] for t in tools)
        check("three tools exposed",
              names == ["render_surface", "scaffold_blueprint", "validate_blueprint"],
              names)
        check("every tool has an inputSchema",
              all(t.get("inputSchema", {}).get("type") == "object" for t in tools))
        check("every tool has a description",
              all(len(t.get("description", "")) > 40 for t in tools))

        print("\n[3] valid blueprint passes clean")
        data, err = structured(srv.call("validate_blueprint",
                                        {"blueprint": VALID_BLUEPRINT}))
        check("valid blueprint accepted", data is not None and data.get("valid"), err)
        if data:
            check("root identified as c1", data.get("root") == "c1", data.get("root"))
            check("component count 9", data.get("components") == 9, data.get("components"))
            check("binds resolved",
                  data.get("binds") == ["confirm", "env", "note"], data.get("binds"))
            check("fired intent tracked",
                  data.get("firedIntents") == ["submit_deploy"], data.get("firedIntents"))
            check("no unused intents",
                  data.get("unusedIntents") == [], data.get("unusedIntents"))

        print("\n[4] hallucination rejections — each at its own gate")
        cases = [
            ("nested tree", NESTED_BLUEPRINT, "gate 2"),
            ("unbound bind", UNBOUND_BLUEPRINT, "gate 5"),
            ("rogue intent", ROGUE_INTENT_BLUEPRINT, "gate 6"),
            ("invented prop", BAD_PROP_BLUEPRINT, "gate 7"),
            ("two roots", TWO_ROOT_BLUEPRINT, "gate 3"),
        ]
        for label, blueprint, gate in cases:
            data, err = structured(srv.call("validate_blueprint",
                                            {"blueprint": blueprint}))
            check("%s rejected at %s" % (label, gate),
                  data is None and err is not None and gate in err, err)

        print("\n[5] malformed input does not crash the server")
        data, err = structured(srv.call("validate_blueprint",
                                        {"blueprint": {"components": []}}))
        check("empty components rejected", data is None and "gate 1" in (err or ""), err)
        data, err = structured(srv.call("validate_blueprint",
                                        {"blueprint": "{not json"}))
        check("unparseable string rejected",
              data is None and "gate 1" in (err or ""), err)
        bad = srv.request("tools/call", {"name": "no_such_tool", "arguments": {}})
        check("unknown tool errors cleanly", "error" in bad, bad)
        check("server still alive after bad calls",
              srv.request("ping").get("result") == {})

        print("\n[6] scaffold — audit intake")
        data, err = structured(srv.call("scaffold_blueprint", AUDIT_SCAFFOLD_SPEC))
        scaffolded = None
        if check("scaffold succeeded", data is not None, err):
            scaffolded = data["blueprint"]
            binds = sorted(
                c["props"]["bind"] for c in scaffolded["components"]
                if c.get("props", {}).get("bind")
            )
            check("all five fields bound",
                  binds == ["deps", "depth", "max_files", "notes", "repo"], binds)
            check("dataModel covers every bind",
                  sorted(scaffolded["dataModel"]) == binds,
                  sorted(scaffolded["dataModel"]))
            check("slider default is 100",
                  scaffolded["dataModel"].get("max_files") == 100)
            check("select default is standard",
                  scaffolded["dataModel"].get("depth") == "standard")
            check("submit intent whitelisted",
                  scaffolded["intents"] == ["submit_audit_scope"],
                  scaffolded["intents"])
            button = [c for c in scaffolded["components"] if c["type"] == "Button"][0]
            check("button payloadKeys match binds",
                  sorted(button["props"]["action"]["payloadKeys"]) == binds,
                  button["props"]["action"])
            # the scaffold must survive the gates it was built against
            again, err2 = structured(srv.call("validate_blueprint",
                                              {"blueprint": scaffolded}))
            check("scaffold revalidates clean",
                  again is not None and again.get("valid"), err2)

        print("\n[7] scaffold rejects bad specs")
        _, err = structured(srv.call("scaffold_blueprint",
                                     {"title": "x", "intent": "i", "fields": []}))
        check("empty fields rejected", err is not None, err)
        _, err = structured(srv.call("scaffold_blueprint", {
            "title": "x", "intent": "i",
            "fields": [{"type": "Button", "label": "nope"}]}))
        check("non-input field type rejected",
              err is not None and "gate 4" in err, err)
        _, err = structured(srv.call("scaffold_blueprint", {
            "title": "x", "intent": "i",
            "fields": [{"type": "Select", "label": "no options"}]}))
        check("select without options rejected", err is not None, err)

        print("\n[8] render — self-contained CSP-safe HTML")
        outdir = tempfile.mkdtemp(prefix="agentsurface-test-")
        out = os.path.join(outdir, "surface-deploy.html")
        data, err = structured(srv.call("render_surface",
                                        {"blueprint": VALID_BLUEPRINT,
                                         "output_path": out}))
        if check("render succeeded", data is not None, err):
            check("file written to requested path", os.path.isfile(out), data)
            check("reported size matches file on disk",
                  data["bytes"] == os.path.getsize(out),
                  (data["bytes"], os.path.getsize(out)))
            check("render reports self-contained", data.get("selfContained") is True)
            html = open(out, encoding="utf-8").read()
            check("placeholder fully replaced", "__BLUEPRINT__" not in html)
            check("no external scripts", "<script src" not in html)
            check("no network calls", "fetch(" not in html and "XMLHttpRequest" not in html)
            check("no eval", "eval(" not in html)
            check("blueprint embedded", "submit_deploy" in html)
            check("intent firewall present", "checkIntent" in html)
            check("substantial output (>10KB)", data["bytes"] > 10000, data["bytes"])
            print("        rendered %d bytes -> %s" % (data["bytes"], out))

        print("\n[9] render refuses an invalid blueprint")
        blocked = os.path.join(outdir, "should-not-exist.html")
        data, err = structured(srv.call("render_surface",
                                        {"blueprint": NESTED_BLUEPRINT,
                                         "output_path": blocked}))
        check("invalid blueprint not rendered",
              data is None and "gate 2" in (err or ""), err)
        check("no file written for rejected blueprint", not os.path.exists(blocked))

        print("\n[10] script-breakout escaping")
        evil = json.loads(json.dumps(VALID_BLUEPRINT))
        evil["components"][2]["props"]["text"] = "</script><script>alert(1)</script>"
        evil_out = os.path.join(outdir, "surface-evil.html")
        data, err = structured(srv.call("render_surface",
                                        {"blueprint": evil,
                                         "output_path": evil_out}))
        if check("blueprint with markup in a text prop still renders",
                 data is not None, err):
            html = open(evil_out, encoding="utf-8").read()
            check("closing script tag neutralized",
                  "</script><script>alert(1)</script>" not in html)
            check("payload escaped as unicode", "\\u003c/script" in html)
            # exactly the script blocks the template itself ships with
            check("no injected script element",
                  html.count("<script>") == 1, html.count("<script>"))

        print("\n[11] scaffold -> validate -> render, end to end")
        if scaffolded:
            e2e = os.path.join(outdir, "surface-audit.html")
            data, err = structured(srv.call("render_surface",
                                            {"blueprint": scaffolded,
                                             "output_path": e2e}))
            if check("scaffolded surface renders", data is not None, err):
                html = open(e2e, encoding="utf-8").read()
                check("audit intent in rendered surface",
                      "submit_audit_scope" in html)
                check("all five labels present",
                      all(lbl in html for lbl in
                          ["Repository", "Depth", "Max files",
                           "Include dependencies", "Notes"]))
                print("        rendered %d bytes -> %s" % (data["bytes"], e2e))
    finally:
        srv.close()

    print("\n" + "=" * 62)
    print("PASSED %d   FAILED %d" % (len(PASS), len(FAIL)))
    if FAIL:
        for name, detail in FAIL:
            print("  FAILED: %s  -> %s" % (name, detail))
        print("=" * 62)
        return 1
    print("ALL GREEN")
    print("=" * 62)
    return 0


if __name__ == "__main__":
    sys.exit(main())
