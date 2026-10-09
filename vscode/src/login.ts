// Browser hand-off login — same protocol as the CLI (cli/mogi_cli/auth.py):
// listen on 127.0.0.1, open <site>/api/auth/cli?port&state, the API redirects the
// browser to http://127.0.0.1:<port>/callback#token=… ; the page posts the fragment back.
import * as crypto from "crypto";
import * as http from "http";
import type { AddressInfo } from "net";
import * as vscode from "vscode";

const STYLE = "font-family:-apple-system,Segoe UI,Helvetica,Arial,sans-serif;background:#0d1117;color:#e6edf3;" +
  "display:flex;flex-direction:column;align-items:center;margin-top:18vh;gap:14px";

const CALLBACK_PAGE = `<!doctype html><meta charset="utf-8"><title>mogi — signing in</title>
<body style="${STYLE}"><div style="font-size:2rem;font-weight:700">mogi</div><div id="m">Finishing sign-in…</div>
<script>
const p = new URLSearchParams(location.hash.slice(1));
fetch("/token", {method: "POST", headers: {"content-type": "application/json"},
  body: JSON.stringify({token: p.get("token"), state: p.get("state"), login: p.get("login")})})
  .then(r => r.text()).then(t => { history.replaceState(null, "", "/callback"); document.open(); document.write(t); document.close(); })
  .catch(e => { document.getElementById("m").textContent = "failed: " + e; });
</script>`;

const donePage = (login: string) => `<!doctype html><meta charset="utf-8"><title>mogi — signed in</title>
<body style="${STYLE}"><div style="font-size:2rem;font-weight:700">mogi</div>
<div style="color:#3fb950;font-size:1.2rem">✓ Signed in as @${login.replace(/[<>&"]/g, "")}</div>
<div style="color:#8b949e">You can close this tab and go back to VS Code.</div>`;

export function login(site: string, timeoutMs = 180_000): Promise<{ token: string; login: string }> {
  return new Promise((resolve, reject) => {
    const state = crypto.randomBytes(16).toString("base64url");
    let done = false;
    const finish = (err?: Error, result?: { token: string; login: string }) => {
      if (done) return;
      done = true;
      clearTimeout(timer);
      server.close();
      if (err) reject(err); else resolve(result!);
    };
    const server = http.createServer((req, res) => {
      const u = new URL(req.url || "/", "http://127.0.0.1");
      if (req.method === "GET" && u.pathname === "/callback") {
        res.writeHead(200, { "content-type": "text/html; charset=utf-8", "cache-control": "no-store" });
        res.end(CALLBACK_PAGE);
        return;
      }
      if (req.method === "POST" && u.pathname === "/token") {
        let body = "";
        req.on("data", c => { body += c; });
        req.on("end", () => {
          let d: { token?: string; state?: string; login?: string } = {};
          try { d = JSON.parse(body || "{}"); } catch { /* fall through */ }
          if (d.state !== state || !d.token) {
            res.writeHead(400, { "content-type": "text/html; charset=utf-8" });
            res.end("<p>state mismatch — start the sign-in again</p>");
            return;
          }
          res.writeHead(200, { "content-type": "text/html; charset=utf-8" });
          res.end(donePage(d.login || ""));
          finish(undefined, { token: d.token, login: d.login || "" });
        });
        return;
      }
      res.writeHead(404);
      res.end();
    });
    const timer = setTimeout(() => finish(new Error("sign-in timed out — no token received")), timeoutMs);
    server.on("error", e => finish(e));
    server.listen(0, "127.0.0.1", () => {
      const port = (server.address() as AddressInfo).port;
      const url = `${site}/api/auth/cli?port=${port}&state=${state}`;
      void vscode.env.openExternal(vscode.Uri.parse(url));
    });
  });
}
