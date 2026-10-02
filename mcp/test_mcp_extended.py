"""Extended checks for mcp/server.py: gate coverage, injection safety, robustness,
and (if Playwright is installed) a real-browser submit test.  Run: python3 mcp/test_mcp_extended.py"""
import json, os, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SERVER = os.path.join(HERE, "server.py")
TEMPLATE = os.path.join(HERE, "..", "skill", "templates", "surface-template.html")

passed = failed = 0
def check(name, cond, detail=""):
    global passed, failed
    if cond: passed += 1
    else:
        failed += 1
        print("  FAIL:", name, "|", str(detail)[:200])
    return cond

class Server:
    def __init__(self, *extra):
        self.p = subprocess.Popen([sys.executable, SERVER, "--template", TEMPLATE, *extra],
                                  stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
        self.n = 0
    def rpc(self, method, params=None):
        self.n += 1
        self.p.stdin.write(json.dumps({"jsonrpc": "2.0", "id": self.n, "method": method, "params": params or {}}) + "\n")
        self.p.stdin.flush()
        return json.loads(self.p.stdout.readline())
    def raw(self, line):
        self.p.stdin.write(line + "\n"); self.p.stdin.flush()
    def tool(self, name, args):
        return self.rpc("tools/call", {"name": name, "arguments": args})["result"]
    def text(self, name, args):
        r = self.tool(name, args)
        return r["isError"], r["content"][0]["text"]
    def close(self):
        self.p.stdin.close(); self.p.wait(timeout=5)

def comp(i, t, props=None, children=None):
    c = {"id": i, "type": t, "props": props or {}}
    if children is not None: c["children"] = children
    return c

def bp(comps, dm=None, intents=None):
    return {"components": comps, "dataModel": dm or {}, "intents": intents or []}

srv = Server()
srv.rpc("initialize", {"protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {"name": "t", "version": "0"}})

# --- each gate rejects, and names itself -------------------------------------
print("gates")
cases = {
    1: ("empty components", bp([])),
    3: ("duplicate ids", bp([comp("a", "Stack", children=["b"]), comp("b", "Text", {"text": "x"}), comp("b", "Text", {"text": "y"})])),
    "3b": ("orphan child", bp([comp("a", "Stack", children=["ghost"])])),
    "3c": ("two roots", bp([comp("a", "Text", {"text": "x"}), comp("b", "Text", {"text": "y"})])),
    "3d": ("two parents", bp([comp("r", "Stack", children=["p", "q"]), comp("p", "Stack", children=["k"]),
                              comp("q", "Stack", children=["k"]), comp("k", "Text", {"text": "x"})])),
    4: ("unknown type", bp([comp("a", "Script", {})])),
    5: ("bind missing from dataModel", bp([comp("a", "TextField", {"label": "x", "bind": "nope"})])),
    6: ("intent not whitelisted", bp([comp("a", "Button", {"label": "go", "action": {"intent": "rm_rf"}})], intents=["ok"])),
    "6b": ("action malformed", bp([comp("a", "Button", {"label": "go", "action": "rm_rf"})])),
    7: ("undocumented prop", bp([comp("a", "Text", {"text": "x", "onclick": "alert(1)"})])),
    8: ("non-string text", bp([comp("a", "Text", {"text": {"html": "<b>"}})])),
}
for key, (label, b) in cases.items():
    gate = str(key)[0]
    err, txt = srv.text("validate_blueprint", {"blueprint": b})
    check(f"{label} -> gate {gate}", err and f"[gate {gate}]" in txt, txt)
    err, txt = srv.text("render_surface", {"blueprint": b})
    check(f"{label} not rendered", err and "<html" not in txt.lower(), txt)
# gate 2 (nested)
err, txt = srv.text("validate_blueprint", {"blueprint": bp([comp("r", "Card", children=[comp("i", "Text", {"text": "x"})])])})
check("nested -> gate 2", err and "[gate 2]" in txt, txt)
# gate 3 cycle
err, txt = srv.text("validate_blueprint", {"blueprint": bp([comp("r", "Stack", children=["a"]), comp("a", "Stack", children=["b"]), comp("b", "Stack", children=["a"])])})
check("cycle rejected", err, txt)

# --- script breakout ----------------------------------------------------------
print("injection")
for payload in ["</script><script>window.pwn=1</script>", "<!--<script>", "</SCRIPT >", " </script>", "a&b<img src=x onerror=1>"]:
    b = bp([comp("r", "Stack", children=["t"]), comp("t", "Text", {"text": payload})])
    r = srv.tool("render_surface", {"blueprint": b})
    html = r["content"][2]["text"] if not r["isError"] else ""
    check(f"renders with payload {payload[:14]!r}", html != "")
    # the real invariant: blueprint region contains no raw '<' at all
    start = html.find('"components"')
    end = html.find("</script>", start)
    region = html[start:end]
    check(f"blueprint region has no raw '<' ({payload[:14]!r})", "<" not in region, region[:120])

# --- robustness: nothing crashes the server ---------------------------------------
print("robustness")
junk = [None, 5, "x", [], {"components": "no"}, {"components": [None]}, {"components": [5]},
        {"components": [{"id": "a", "type": "Text", "props": "oops"}]},
        {"components": [{"id": "a", "type": "Stack", "children": "abc"}]},
        {"components": [{"id": ["a"], "type": "Text"}]},
        {"components": [{"id": "a", "type": "Text", "props": {"text": "x"}}], "dataModel": [], "intents": "x"},
        "{not json"]
for j in junk:
    for tool in ("validate_blueprint", "render_surface"):
        try:
            r = srv.tool(tool, {"blueprint": j})
            check(f"{tool}({str(j)[:30]!r}) answered cleanly", isinstance(r.get("isError"), bool), r)
        except Exception as e:
            check(f"{tool}({str(j)[:30]!r}) answered", False, e)
for bad in ("not json at all", "{", '{"jsonrpc":"2.0"}', "[]", '{"jsonrpc":"2.0","id":99,"method":"nope"}'):
    srv.raw(bad)
srv.n = 99  # reply to unknown method has id 99
resp = json.loads(srv.p.stdout.readline())
check("unknown method -> -32601", resp.get("error", {}).get("code") == -32601, resp)
check("server alive after junk", srv.rpc("ping").get("result") == {})
err, txt = srv.text("no_such_tool", {})
check("unknown tool is isError", err)
err, txt = srv.text("scaffold_blueprint", {"kind": "nope"})
check("unknown scaffold kind rejected", err, txt)
for kind, data in [("dashboard", {"stats": [{"label": "a", "value": 1}], "kv": [{"label": "k", "value": "v"}]}),
                   ("form", {"fields": [{"kind": "slider", "bind": "s"}, {"kind": "checkbox", "bind": "c"}]}),
                   ("taskboard", {"tasks": [{"task": "t", "status": "s", "owner": "o"}]}),
                   ("comparison", {"columns": ["a", "b"], "rows": [["1", "2"]]}),
                   ("dashboard", {}), ("form", {}), ("taskboard", {}), ("comparison", {})]:
    err, txt = srv.text("scaffold_blueprint", {"kind": kind, "title": "T", "data": data})
    check(f"scaffold {kind} {'(empty)' if not data else ''} validates", not err and "VALID" in json.loads(txt)["validation"], txt)
srv.close()

# --- template autodiscovery ---------------------------------------------------------
print("discovery")
env = {k: v for k, v in os.environ.items() if k != "AGENTSURFACE_TEMPLATE"}
out = subprocess.run([sys.executable, SERVER, "--print-template"], capture_output=True, text=True, env=env).stdout.strip()
check("template found with no flags (README config works)", out.endswith("surface-template.html") and os.path.exists(out), out)

# --- real browser ----------------------------------------------------------------------
print("browser")
try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sync_playwright = None
    print("  (skipped: playwright not installed)")
if sync_playwright:
    s2 = Server()
    s2.rpc("initialize", {"protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {"name": "t", "version": "0"}})
    scaf = json.loads(s2.text("scaffold_blueprint", {"kind": "form", "title": "Audit </script> Intake",
        "data": {"fields": [{"kind": "text", "label": "Repo", "bind": "repo"}]}})[1])["blueprint"]
    html = s2.tool("render_surface", {"blueprint": scaf})["content"][2]["text"]
    s2.close()
    path = os.path.join(tempfile.mkdtemp(), "s.html")
    open(path, "w").write(html)
    with sync_playwright() as p:
        b = p.chromium.launch(); pg = b.new_page()
        errs = []
        pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)
        pg.goto("file://" + path); pg.wait_for_timeout(500)
        check("no page/console errors", not errs, errs)
        check("title with '</script>' rendered as text", "</script>" in pg.inner_text("body"))
        check("no injected script exec", pg.evaluate("document.scripts.length") <= 2)
        pg.fill("input[type=text]", "RemyLoveLogicAI/agentsurface")
        pg.click("button.act"); pg.wait_for_timeout(300)
        check("envelope panel shown", pg.is_visible("#result.show"))
        env_txt = pg.inner_text("#envelope") if pg.is_visible("#envelope") else ""
        check("envelope carries intent + bound value", "submit" in env_txt and "RemyLoveLogicAI/agentsurface" in env_txt, env_txt)
        b.close()

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
