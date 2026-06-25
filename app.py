#!/usr/bin/env python3
"""Local web UI for the skill factory: Generate -> 5 ranked suggestions -> one-click install.

Bound to 127.0.0.1 only: it can write into ~/.claude/skills and run the generator, so it must
never be exposed off-machine. The install endpoint is diff-guarded in the UI (the page shows the
diff and asks you to confirm before any overwrite). Stdlib only.
"""
import difflib
import http.server
import json
import os
import socketserver
import subprocess
import threading
import webbrowser
from urllib.parse import urlparse, parse_qs

REPO = os.path.dirname(os.path.abspath(__file__))
PROPOSALS = os.path.join(REPO, "proposals")
SKILLS = os.path.expanduser("~/.claude/skills")
PORT = 4321

# ponytail: generation runs synchronously in the request thread (~2-4 min); fine on localhost
# with a ThreadingHTTPServer. If it ever times out, switch to background job + status polling.


def latest_dir():
    if not os.path.isdir(PROPOSALS):
        return None
    dirs = [os.path.join(PROPOSALS, d) for d in os.listdir(PROPOSALS)
            if os.path.isfile(os.path.join(PROPOSALS, d, "proposals.json"))]
    return max(dirs, key=os.path.getmtime) if dirs else None


def installed_md(name):
    p = os.path.join(SKILLS, name, "SKILL.md")
    return open(p, encoding="utf-8").read() if os.path.isfile(p) else None


def load_latest():
    d = latest_dir()
    if not d:
        return {"stamp": None, "candidates": []}
    data = json.load(open(os.path.join(d, "proposals.json"), encoding="utf-8"))
    for c in data["candidates"]:
        cur = installed_md(c["name"])
        c["exists"] = cur is not None
        c["installed"] = cur is not None and cur.strip() == (c.get("skill_md") or "").strip()
    return data


def skill_detail(name):
    d = latest_dir()
    cand = None
    if d:
        data = json.load(open(os.path.join(d, "proposals.json"), encoding="utf-8"))
        cand = next((c for c in data["candidates"] if c["name"] == name), None)
    proposed = (cand or {}).get("skill_md", "")
    cur = installed_md(name)
    diff = ""
    if cur is not None:
        diff = "".join(difflib.unified_diff(
            cur.splitlines(keepends=True), proposed.splitlines(keepends=True),
            fromfile=f"current/{name}", tofile=f"proposed/{name}"))
    return {"name": name, "skill_md": proposed, "exists": cur is not None, "diff": diff}


def install(name):
    d = latest_dir()
    if not d:
        return {"ok": False, "message": "no proposals to install"}
    target = os.path.join(d, name)
    if not os.path.isfile(os.path.join(target, "SKILL.md")):
        return {"ok": False, "message": f"no drafted SKILL.md for {name}"}
    # The UI already showed the diff and the user confirmed -> --force (install.sh stays the
    # single writer + the diff-guard for CLI use).
    r = subprocess.run(["bash", os.path.join(REPO, "install.sh"), target, "--force"],
                       capture_output=True, text=True)
    return {"ok": r.returncode == 0, "message": (r.stdout + r.stderr).strip()}


def generate(days):
    r = subprocess.run(["bash", os.path.join(REPO, "factory.sh"), str(days)],
                       capture_output=True, text=True, timeout=600)
    if r.returncode != 0:
        return {"ok": False, "message": (r.stdout + r.stderr).strip()[-2000:]}
    out = load_latest()
    out["ok"] = True
    return out


class Handler(http.server.BaseHTTPRequestHandler):
    def _send(self, code, body, ctype="application/json"):
        b = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj), "application/json")

    def log_message(self, *a):
        pass  # quiet

    def do_GET(self):
        u = urlparse(self.path)
        if u.path == "/":
            return self._send(200, PAGE, "text/html; charset=utf-8")
        if u.path == "/api/latest":
            return self._json(load_latest())
        if u.path == "/api/skill":
            name = (parse_qs(u.query).get("name") or [""])[0]
            return self._json(skill_detail(name))
        return self._send(404, "not found", "text/plain")

    def _body_json(self):
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n) or "{}")

    def do_POST(self):
        u = urlparse(self.path)
        if u.path == "/api/install":
            name = self._body_json().get("name", "")
            return self._json(install(name))
        if u.path == "/api/generate":
            days = int(self._body_json().get("days", 30))
            try:
                return self._json(generate(days))
            except subprocess.TimeoutExpired:
                return self._json({"ok": False, "message": "generation timed out (>10min)"}, 504)
        if u.path == "/api/quit":
            self._json({"ok": True})
            threading.Thread(target=self.server.shutdown, daemon=True).start()
            return
        return self._send(404, "not found", "text/plain")


PAGE = r"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Skill Factory</title>
<style>
:root{--bg:#0e0f13;--card:#181a21;--line:#262a35;--ink:#e8eaf0;--mut:#9aa3b2;--acc:#7c5cff;--ok:#34d399;--warn:#f59e0b}
*{box-sizing:border-box}body{margin:0;font:15px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;background:var(--bg);color:var(--ink)}
header{position:sticky;top:0;display:flex;align-items:center;gap:14px;padding:16px 22px;background:rgba(14,15,19,.85);backdrop-filter:blur(8px);border-bottom:1px solid var(--line);z-index:5}
header h1{font-size:17px;margin:0;font-weight:600;letter-spacing:.2px}
header .sub{color:var(--mut);font-size:13px}
header .spacer{flex:1}
button{font:inherit;border:1px solid var(--line);background:var(--card);color:var(--ink);padding:8px 14px;border-radius:9px;cursor:pointer;transition:.15s}
button:hover{border-color:var(--acc)}
button.primary{background:var(--acc);border-color:var(--acc);color:#fff;font-weight:600}
button.primary:hover{filter:brightness(1.08)}
button.ghost{background:transparent}
button:disabled{opacity:.5;cursor:default}
main{max-width:880px;margin:0 auto;padding:24px 22px 80px}
.card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:18px 20px;margin:14px 0}
.card .top{display:flex;align-items:flex-start;gap:14px}
.rank{flex:none;width:34px;height:34px;border-radius:9px;background:#23202e;color:var(--acc);font-weight:700;display:grid;place-items:center}
.rank.one{background:var(--acc);color:#fff}
.card h2{margin:0;font-size:17px;font-family:ui-monospace,SFMono-Regular,Menlo,monospace}
.card .desc{color:var(--ink);margin:2px 0 0}
.score{margin-left:auto;flex:none;color:var(--mut);font-size:13px;text-align:right}
.score b{color:var(--ink);font-size:15px}
.tag{display:inline-block;font-size:11px;color:var(--mut);border:1px solid var(--line);border-radius:20px;padding:1px 9px;margin-top:8px}
.ev{color:var(--mut);font-size:13.5px;margin:10px 0 0;border-left:2px solid var(--line);padding-left:12px}
.actions{display:flex;gap:9px;margin-top:14px;flex-wrap:wrap}
.badge{font-size:12px;padding:4px 10px;border-radius:7px}
.badge.ok{background:rgba(52,211,153,.12);color:var(--ok)}
.badge.upd{background:rgba(245,158,11,.12);color:var(--warn)}
.empty{text-align:center;color:var(--mut);padding:70px 0}
.empty h2{color:var(--ink);font-weight:600}
.modal{position:fixed;inset:0;background:rgba(0,0,0,.6);display:none;align-items:center;justify-content:center;padding:24px;z-index:10}
.modal.show{display:flex}
.sheet{background:var(--card);border:1px solid var(--line);border-radius:14px;max-width:760px;width:100%;max-height:84vh;display:flex;flex-direction:column}
.sheet header{position:static;background:none;border-bottom:1px solid var(--line)}
.sheet .body{overflow:auto;padding:18px 20px}
pre{white-space:pre-wrap;word-break:break-word;font:12.5px/1.55 ui-monospace,SFMono-Regular,Menlo,monospace;background:#0b0c10;border:1px solid var(--line);border-radius:10px;padding:14px;margin:0}
pre.diff .add{color:var(--ok)}pre.diff .del{color:#f87171}pre.diff .hdr{color:var(--acc)}
.sheet .foot{display:flex;gap:10px;justify-content:flex-end;padding:14px 20px;border-top:1px solid var(--line)}
.overlay{position:fixed;inset:0;background:rgba(14,15,19,.82);display:none;align-items:center;justify-content:center;flex-direction:column;gap:18px;z-index:20}
.overlay.show{display:flex}
.spin{width:38px;height:38px;border:3px solid var(--line);border-top-color:var(--acc);border-radius:50%;animation:s 1s linear infinite}
@keyframes s{to{transform:rotate(360deg)}}
.toast{position:fixed;bottom:22px;left:50%;transform:translateX(-50%);background:var(--card);border:1px solid var(--acc);padding:11px 18px;border-radius:10px;display:none;z-index:30}
.toast.show{display:block}
</style></head><body>
<header>
  <h1>🏭 Skill Factory</h1><span class="sub" id="stamp"></span>
  <span class="spacer"></span>
  <select id="days" title="scan window">
    <option value="14">14 days</option><option value="30" selected>30 days</option><option value="60">60 days</option>
  </select>
  <button class="primary" id="gen">✨ Generate suggestions</button>
  <button class="ghost" id="quit" title="stop the server">Quit</button>
</header>
<main id="main"></main>

<div class="modal" id="modal"><div class="sheet">
  <header><h1 id="m-title" style="font-family:ui-monospace,monospace"></h1><span class="spacer"></span>
    <button class="ghost" onclick="closeModal()">Close</button></header>
  <div class="body"><pre id="m-pre"></pre></div>
  <div class="foot" id="m-foot"></div>
</div></div>

<div class="overlay" id="overlay"><div class="spin"></div><div id="ov-text">Generating…</div>
  <div class="sub" style="color:var(--mut);font-size:13px">reading your sessions, clustering, drafting 5 skills (~2-4 min)</div></div>
<div class="toast" id="toast"></div>

<script>
const $=s=>document.querySelector(s);
let DATA={candidates:[]};
function esc(s){return (s||"").replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]))}
function toast(m){const t=$("#toast");t.textContent=m;t.classList.add("show");setTimeout(()=>t.classList.remove("show"),2600)}

function render(){
  $("#stamp").textContent=DATA.stamp?("· "+DATA.stamp.replace("_"," ")):"";
  const m=$("#main");
  if(!DATA.candidates.length){m.innerHTML='<div class="empty"><h2>No suggestions yet</h2><p>Hit “Generate suggestions” — it reads how you actually work and drafts 5 skills you could add.</p></div>';return}
  m.innerHTML=DATA.candidates.map((c,i)=>{
    let badge="";
    if(c.installed)badge='<span class="badge ok">✓ installed</span>';
    else if(c.exists)badge='<span class="badge upd">update available</span>';
    const addLabel=c.installed?"Re-install":(c.exists?"Overwrite…":"Add to skills");
    return `<div class="card"><div class="top">
      <div class="rank ${i==0?'one':''}">${i+1}</div>
      <div><h2>${esc(c.name)}</h2><div class="desc">${esc(c.description)}</div>
        ${c.pillar?`<span class="tag">${esc(c.pillar)}</span>`:""}</div>
      <div class="score"><b>${c.score??"-"}</b>/10</div></div>
      ${c.evidence?`<div class="ev">${esc(c.evidence)}</div>`:""}
      <div class="actions">
        <button onclick="view('${esc(c.name)}')">View SKILL.md</button>
        <button class="primary" ${c.installed?"disabled":""} onclick="addSkill('${esc(c.name)}')">${addLabel}</button>
        ${badge}
      </div></div>`}).join("");
}
function colorDiff(d){return esc(d).split("\n").map(l=>{
  if(l.startsWith("+")&&!l.startsWith("+++"))return `<span class="add">${l}</span>`;
  if(l.startsWith("-")&&!l.startsWith("---"))return `<span class="del">${l}</span>`;
  if(l.startsWith("@@")||l.startsWith("+++")||l.startsWith("---"))return `<span class="hdr">${l}</span>`;
  return l}).join("\n")}

async function view(name){
  const r=await fetch("/api/skill?name="+encodeURIComponent(name));const d=await r.json();
  $("#m-title").textContent=name;$("#m-pre").className="";$("#m-pre").textContent=d.skill_md||"(empty)";
  $("#m-foot").innerHTML='<button class="ghost" onclick="closeModal()">Close</button>'+
    `<button class="primary" onclick="addSkill('${esc(name)}')">Add to skills</button>`;
  $("#modal").classList.add("show");
}
async function addSkill(name){
  const r=await fetch("/api/skill?name="+encodeURIComponent(name));const d=await r.json();
  if(d.exists&&d.diff){
    $("#m-title").textContent="Overwrite "+name+" ?";
    $("#m-pre").className="diff";$("#m-pre").innerHTML=colorDiff(d.diff);
    $("#m-foot").innerHTML='<button class="ghost" onclick="closeModal()">Cancel</button>'+
      `<button class="primary" onclick="doInstall('${esc(name)}')">Overwrite &amp; install</button>`;
  }else{
    $("#m-title").textContent="Add “"+name+"” to your skills?";
    $("#m-pre").className="";$("#m-pre").textContent=d.skill_md||"";
    $("#m-foot").innerHTML='<button class="ghost" onclick="closeModal()">Cancel</button>'+
      `<button class="primary" onclick="doInstall('${esc(name)}')">Add to skills</button>`;
  }
  $("#modal").classList.add("show");
}
async function doInstall(name){
  closeModal();
  const r=await fetch("/api/install",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({name})});
  const d=await r.json();
  toast(d.ok?("✓ Installed "+name):("Failed: "+d.message));
  if(d.ok)await refresh();
}
function closeModal(){$("#modal").classList.remove("show")}

async function refresh(){const r=await fetch("/api/latest");DATA=await r.json();render()}
$("#gen").onclick=async()=>{
  $("#overlay").classList.add("show");$("#gen").disabled=true;
  try{
    const r=await fetch("/api/generate",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({days:+$("#days").value})});
    const d=await r.json();
    if(d.ok){DATA=d;render();toast("✓ "+(DATA.candidates.length)+" suggestions")}
    else toast("Generate failed: "+(d.message||"").slice(0,120));
  }catch(e){toast("Generate error: "+e)}
  finally{$("#overlay").classList.remove("show");$("#gen").disabled=false}
};
$("#quit").onclick=async()=>{await fetch("/api/quit",{method:"POST"});document.body.innerHTML='<div class="empty"><h2>Skill Factory stopped</h2><p>You can close this tab.</p></div>'};
refresh();
</script></body></html>"""


def main():
    socketserver.TCPServer.allow_reuse_address = True
    try:
        httpd = socketserver.ThreadingTCPServer(("127.0.0.1", PORT), Handler)
    except OSError:
        print(f"Port {PORT} busy — assuming Skill Factory already runs. Opening browser.")
        webbrowser.open(f"http://127.0.0.1:{PORT}/")
        return
    url = f"http://127.0.0.1:{PORT}/"
    print(f"Skill Factory UI: {url}  (Ctrl-C or the Quit button to stop)")
    if not os.environ.get("SF_NO_OPEN"):  # set SF_NO_OPEN=1 for headless/screenshot runs
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    httpd.server_close()
    print("stopped.")


if __name__ == "__main__":
    main()
