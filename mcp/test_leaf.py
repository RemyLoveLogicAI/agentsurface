import json, subprocess

TEMPLATE = "/app/.agents/skills/agent-surface/templates/surface-template.html"

bp = {
    "surface": {"title": "LoveLogic Consulting — Ops", "subtitle": "leaf layer live test"},
    "components": [
        {"id": "root", "type": "Stack", "props": {"direction": "column", "gap": "16"}, "children": ["rev", "audit", "approve"]},
        {"id": "rev", "type": "Stat", "props": {"label": "Revenue", "value": 0, "unit": "USD"}},
        {"id": "audit", "type": "KeyValue", "props": {"label": "Active SKU", "value": "$1,500 Governance Audit"}},
        {"id": "approve", "type": "Button", "props": {"label": "Approve queue", "action": {"intent": "approve"}}},
    ],
    "dataModel": {}, "intents": ["approve"]
}

msgs = [
    {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {"name": "t", "version": "0"}}},
    {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "render_surface", "arguments": {"blueprint": bp, "leaf": True}}},
]
proc = subprocess.run(["python3", "server.py", "--template", TEMPLATE],
    input="\n".join(json.dumps(m) for m in msgs), capture_output=True, text=True)
resp = None
for line in proc.stdout.strip().split("\n"):
    r = json.loads(line)
    if r.get("id") == 2: resp = r["result"]
print("isError:", resp["isError"])
print("report:", resp["content"][0]["text"])
html = resp["content"][2]["text"]
print("html bytes:", len(html))
checks = {
    "leaf css injected": ".leaf-pin" in html,
    "leaf js injected": "leaf_feedback" in html,
    "leaf module imported once": html.count("leaf layer") >= 0 and "data-cid" in html,
    "blueprint injected": "Governance Audit" in html,
    "doctype intact": html.startswith("<!DOCTYPE html>"),
    "single body close": html.count("</body>") == 1,
}
for k, v in checks.items(): print(f"  {k}: {v}")
open("surface-leaf-demo.html", "w").write(html)
print("saved surface-leaf-demo.html")
