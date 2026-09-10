import json, subprocess

TEMPLATE = "/app/.agents/skills/agent-surface/templates/surface-template.html"

valid_bp = {
    "components": [
        {"id": "root", "type": "Card", "props": {"padding": "16"}, "children": ["title", "stats", "btn"]},
        {"id": "title", "type": "Heading", "props": {"text": "Fleet Board", "level": 2}},
        {"id": "stats", "type": "Stat", "props": {"label": "Agents", "value": 5, "unit": "online"}},
        {"id": "btn", "type": "Button", "props": {"label": "Approve", "action": {"intent": "approve"}}},
    ],
    "dataModel": {}, "intents": ["approve"]
}
nested_bp = {
    "components": [
        {"id": "root", "type": "Card", "props": {}, "children": [
            {"id": "inner", "type": "Stat", "props": {"label": "x", "value": 1}}]},
    ], "dataModel": {}, "intents": []
}

msgs = [
    {"jsonrpc": "2.0", "id": 1, "method": "initialize",
     "params": {"protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {"name": "test", "version": "0"}}},
    {"jsonrpc": "2.0", "method": "notifications/initialized"},
    {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
    {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
     "params": {"name": "validate_blueprint", "arguments": {"blueprint": valid_bp}}},
    {"jsonrpc": "2.0", "id": 4, "method": "tools/call",
     "params": {"name": "validate_blueprint", "arguments": {"blueprint": nested_bp}}},
    {"jsonrpc": "2.0", "id": 5, "method": "tools/call",
     "params": {"name": "scaffold_blueprint", "arguments": {
         "kind": "form", "title": "Audit Intake",
         "data": {"fields": [
             {"kind": "text", "label": "Company", "bind": "company", "required": True},
             {"kind": "select", "label": "Tier", "bind": "tier", "options": ["$500 quickscan", "$1500 audit", "$5000 audit+fix"]}]}}}},
    {"jsonrpc": "2.0", "id": 6, "method": "tools/call",
     "params": {"name": "render_surface", "arguments": {"blueprint": valid_bp}}},
]

proc = subprocess.run(
    ["python3", "server.py", "--template", TEMPLATE],
    input="\n".join(json.dumps(m) for m in msgs), capture_output=True, text=True)

print("--- STDERR:", proc.stderr[:500])
outputs = {}
for line in proc.stdout.strip().split("\n"):
    r = json.loads(line)
    outputs[r.get("id")] = r

print("1) initialize:", json.dumps(outputs[1]["result"]["serverInfo"]))
tools = outputs[2]["result"]["tools"]
print("2) tools/list:", [t["name"] for t in tools])
print("3) validate valid:", outputs[3]["result"]["content"][0]["text"][:120])
r4 = outputs[4]["result"]
print("4) validate nested -> isError:", r4["isError"], "|", r4["content"][0]["text"][:110])
sc = json.loads(outputs[5]["result"]["content"][0]["text"])
print("5) scaffold:", sc["validation"][:80])
render = outputs[6]["result"]
html = render["content"][2]["text"]
print("6) render: valid =", render["content"][0]["text"][:60], "| html bytes =", len(html), "| has DOCTYPE:", html.startswith("<!DOCTYPE html>"), "| injected:", '"Fleet Board"' in html)
