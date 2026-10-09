"""Browser hand-off login.

`mogi login` starts a listener on 127.0.0.1:<random port> and opens
`<site>/api/auth/cli?port=…&state=…` in the browser. The API (after GitHub login if
the browser has no session yet) redirects to `http://127.0.0.1:<port>/callback#token=…`.
The token rides in the URL fragment, which the browser never sends to any server;
the tiny page served here reads it from `location.hash` and POSTs it back to this
process, which verifies the anti-CSRF `state` and saves it.
"""
from __future__ import annotations

import html
import json
import secrets
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse

STYLE = ("font-family:-apple-system,Segoe UI,Helvetica,Arial,sans-serif;background:#0d1117;"
         "color:#e6edf3;display:flex;flex-direction:column;align-items:center;"
         "margin-top:18vh;gap:14px")

CALLBACK_PAGE = f"""<!doctype html><meta charset="utf-8"><title>mogi — signing in</title>
<body style="{STYLE}"><div style="font-size:2rem;font-weight:700">mogi</div><div id="m">Finishing sign-in…</div>
<script>
const p = new URLSearchParams(location.hash.slice(1));
fetch("/token", {{method: "POST", headers: {{"content-type": "application/json"}},
  body: JSON.stringify({{token: p.get("token"), state: p.get("state"), login: p.get("login")}})}})
  .then(r => r.text()).then(t => {{
    history.replaceState(null, "", "/callback");
    document.open(); document.write(t); document.close();
  }})
  .catch(e => {{ document.getElementById("m").textContent = "failed: " + e; }});
</script>"""

DONE_PAGE = f"""<!doctype html><meta charset="utf-8"><title>mogi — signed in</title>
<body style="{STYLE}"><div style="font-size:2rem;font-weight:700">mogi</div>
<div style="color:#3fb950;font-size:1.2rem">✓ Signed in as @{{login}}</div>
<div style="color:#8b949e">You can close this tab and go back to your terminal / editor.</div>"""


def login(site: str, timeout_s: int = 180, open_browser: bool = True) -> dict:
    state = secrets.token_urlsafe(16)
    result: dict = {}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):  # keep the terminal quiet
            pass

        def _send(self, body: str, status: int = 200):
            data = body.encode()
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            if urlparse(self.path).path != "/callback":
                self._send("<p>not found</p>", 404)
                return
            self._send(CALLBACK_PAGE)

        def do_POST(self):
            if urlparse(self.path).path != "/token":
                self._send("<p>not found</p>", 404)
                return
            n = int(self.headers.get("Content-Length") or 0)
            try:
                data = json.loads(self.rfile.read(n).decode() or "{}")
            except ValueError:
                data = {}
            if data.get("state") != state or not data.get("token"):
                self._send("<p>state mismatch — start <code>mogi login</code> again</p>", 400)
                return
            result.update(token=data["token"], login=data.get("login", ""))
            self._send(DONE_PAGE.replace("{login}", html.escape(result["login"])))

    srv = HTTPServer(("127.0.0.1", 0), Handler)
    port = srv.server_address[1]
    url = f"{site.rstrip('/')}/api/auth/cli?port={port}&state={state}"
    print("Opening your browser to sign in with GitHub…")
    print(f"  {url}")
    print("(if nothing opens, paste that URL into a browser on this machine)")
    if open_browser:
        webbrowser.open(url)
    srv.timeout = 1
    deadline = time.time() + timeout_s
    try:
        while not result and time.time() < deadline:
            srv.handle_request()
    finally:
        srv.server_close()
    if not result:
        raise TimeoutError("login timed out — no token received")
    return result
