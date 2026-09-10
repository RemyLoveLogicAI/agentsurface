"""Leaf layer for AgentSurface — anchored-collaboration feedback on rendered components.

Implements Leaf's anchored-collaboration model natively: the user pins comments to
specific components by id, and copies a structured leaf envelope back to the agent.
All text via textContent, zero network calls, zero external scripts — CSP-safe.

Envelope format (paste back to the agent, same hydrate loop as intent envelopes):
  {"type": "leaf_feedback", "surface": "<title>", "comments":
   [{"componentId": "<data-cid>", "text": "..."}], "ts": "<iso>"}

Used by server.py: render_surface(blueprint, leaf=true) -> inject_leaf(html).
"""

LEAF_CSS = """<style>
.leaf-host{position:relative}
.leaf-pin{position:absolute;top:6px;right:6px;z-index:40;opacity:0;transition:opacity .15s;
  background:var(--panel2);border:1px solid var(--line);border-radius:8px;color:var(--text);
  font-size:.85rem;padding:2px 7px;cursor:pointer;line-height:1.4}
.leaf-host:hover .leaf-pin{opacity:1}
.leaf-note{margin-top:8px;padding:8px 10px;border-left:3px solid var(--accent);background:var(--panel2);
  border-radius:6px;font-size:.85rem;color:var(--text);white-space:pre-wrap}
.leaf-note .la{color:var(--muted);font-size:.72rem;display:block;margin-bottom:2px}
#leaf-tray{position:fixed;bottom:14px;right:14px;z-index:50}
#leaf-modal{position:fixed;inset:0;z-index:60;display:flex;align-items:center;justify-content:center;
  background:rgba(0,0,0,.55)}
#leaf-modal .box{background:var(--panel);border:1px solid var(--line);border-radius:10px;
  padding:16px;width:min(92vw,420px);display:flex;flex-direction:column;gap:10px}
#leaf-modal .cid{font-family:monospace;color:var(--accent);font-size:.78rem}
#leaf-modal textarea{background:var(--panel2);border:1px solid var(--line);border-radius:8px;
  color:var(--text);font-family:inherit;font-size:.9rem;padding:10px;min-height:90px;resize:vertical}
#leaf-modal .row{display:flex;gap:8px;justify-content:flex-end}
#leaf-modal pre{background:var(--panel2);border:1px solid var(--line);border-radius:8px;padding:10px;
  font-size:.75rem;white-space:pre-wrap;word-break:break-word;max-height:44vh;overflow:auto}
</style>"""

LEAF_JS = """<script>
"use strict";
(function(){
  var comments = [];
  var target = null;

  function el(tag, cls, text){
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text !== undefined) e.textContent = text;
    return e;
  }

  function modal(){
    var m = document.getElementById("leaf-modal");
    if (m) return m;
    m = el("div"); m.id = "leaf-modal";
    var box = el("div", "box"); m.appendChild(box);
    document.body.appendChild(m);
    m.addEventListener("click", function(ev){ if (ev.target === m) m.style.display = "none"; });
    return m;
  }

  function openComposer(host){
    target = host;
    var m = modal(), box = m.firstChild;
    box.textContent = "";
    box.appendChild(el("div", "cid", "annotate #" + host.dataset.cid));
    var ta = document.createElement("textarea");
    ta.placeholder = "Feedback pinned to this component...";
    box.appendChild(ta);
    var row = el("div", "row");
    var cancel = el("button", "act", "Cancel");
    cancel.style.background = "var(--panel2)"; cancel.style.border = "1px solid var(--line)"; cancel.style.color = "var(--text)";
    cancel.addEventListener("click", function(){ m.style.display = "none"; });
    var pin = el("button", "act", "Pin comment");
    pin.addEventListener("click", function(){
      var text = ta.value.trim();
      if (!text) { ta.focus(); return; }
      comments.push({ componentId: target.dataset.cid, text: text });
      var note = el("div", "leaf-note");
      note.appendChild(el("span", "la", "leaf #" + target.dataset.cid));
      note.appendChild(document.createTextNode(text));
      target.appendChild(note);
      updateTray();
      m.style.display = "none";
    });
    row.appendChild(cancel); row.appendChild(pin);
    box.appendChild(row);
    m.style.display = "flex";
    ta.focus();
  }

  function updateTray(){
    var b = document.getElementById("leaf-tray-btn");
    if (b) b.textContent = "🍃 Copy leaf feedback (" + comments.length + ")";
  }

  function showEnvelope(){
    var m = modal(), box = m.firstChild;
    box.textContent = "";
    var env = {
      type: "leaf_feedback",
      surface: (BLUEPRINT.surface && BLUEPRINT.surface.title) || "",
      comments: comments,
      ts: new Date().toISOString()
    };
    box.appendChild(el("div", "cid", "leaf envelope — copy this back to the agent"));
    var pre = el("pre", null, JSON.stringify(env, null, 2));
    box.appendChild(pre);
    var row = el("div", "row");
    var close = el("button", "act", "Close");
    close.style.background = "var(--panel2)"; close.style.border = "1px solid var(--line)"; close.style.color = "var(--text)";
    close.addEventListener("click", function(){ m.style.display = "none"; });
    var copy = el("button", "act", "Copy envelope");
    copy.addEventListener("click", function(){
      var r = document.createRange(); r.selectNodeContents(pre);
      var sel = window.getSelection(); sel.removeAllRanges(); sel.addRange(r);
      try { document.execCommand("copy"); } catch (e) {}
      if (navigator.clipboard && env) {
        navigator.clipboard.writeText(JSON.stringify(env, null, 2)).catch(function(){});
      }
      copy.textContent = "Copied";
      setTimeout(function(){ copy.textContent = "Copy envelope"; }, 1200);
    });
    row.appendChild(close); row.appendChild(copy);
    box.appendChild(row);
    m.style.display = "flex";
  }

  function init(){
    var hosts = document.querySelectorAll("[data-cid]");
    var i;
    for (i = 0; i < hosts.length; i++) {
      (function(host){
        host.classList.add("leaf-host");
        var b = el("button", "leaf-pin", "🍃");
        b.type = "button";
        b.title = "annotate #" + host.dataset.cid;
        b.addEventListener("click", function(ev){ ev.stopPropagation(); openComposer(host); });
        host.appendChild(b);
      })(hosts[i]);
    }
    var tray = el("div"); tray.id = "leaf-tray";
    var btn = el("button", "act", "🍃 Copy leaf feedback (0)");
    btn.id = "leaf-tray-btn";
    btn.addEventListener("click", showEnvelope);
    tray.appendChild(btn);
    document.body.appendChild(tray);
  }

  init();
})();
</script>"""


def inject_leaf(html):
    """Inject the leaf layer into a rendered AgentSurface HTML file (before </body>)."""
    if "</body>" not in html:
        raise ValueError("no </body> found — not a complete rendered surface")
    return html.replace("</body>", LEAF_CSS + LEAF_JS + "</body>", 1)
