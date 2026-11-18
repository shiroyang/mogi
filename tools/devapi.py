#!/usr/bin/env python3
"""A local mogi API for UI work: the real handlers, an in-memory table, the real corpus.

    python3 tools/devapi.py /path/to/真題                      # → http://127.0.0.1:8787
    cd web && MOGI_SITE=http://127.0.0.1:8787 MOGI_CONFIG=/dev/null npm run dev

Nothing here talks to AWS or GitHub.
You are signed in as a local user, and the judge runs on this machine.
State lives in memory and is gone when the server stops.

Dev-only routes:
    POST /dev/clock?days=3              move the clock forward (a redo or a review comes due)
    GET  /dev/state                     your progress and review rows
    GET  /dev/reference?pid=Amazon/B36  a reference solution, to type in when testing a solve
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent))
from localbackend import Backend  # noqa: E402


def seed_solved(backend: Backend, pid: str, reference: str) -> None:
    """Mark one problem as solved a while ago, with the accepted submission behind it."""
    then = backend.now() - 89 * 86400
    sk = f"{then * 1000:013d}#seeded"
    backend.table.put_item(Item={
        "pk": f"SUB#{pid}", "sk": sk, "user": backend.user, "mode": "submit", "code": reference,
        "verdict": "AC", "passed": 10, "total": 10, "ms": 62, "detail": "10/10 checks passed",
        "created": then, "gsi1pk": f"USER#{backend.user}", "gsi1sk": sk, "prob": pid})
    backend.table.put_item(Item={
        "pk": f"USER#{backend.user}", "sk": f"PROG#{pid}", "status": "solved", "attempts": 2,
        "solved_at": then, "last_at": then, "best_ms": 62, "ac_sub": sk})


def make_handler(backend: Backend):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, fmt, *args):  # one short line per request
            sys.stderr.write(f"  {self.command} {self.path.split('?')[0]} → {args[1] if len(args) > 1 else ''}\n")

        def _send(self, status: int, body: str, headers: dict | None = None, cookies: list[str] | None = None):
            data = body.encode()
            self.send_response(status)
            for k, v in (headers or {"content-type": "application/json"}).items():
                self.send_header(k, v)
            for c in cookies or []:
                self.send_header("set-cookie", c)
            self.send_header("content-length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _dev(self, url) -> None:
            query = dict(parse_qsl(url.query))
            if url.path == "/dev/clock":
                if self.command == "POST":
                    backend.advance(days=float(query.get("days", 0)), seconds=int(query.get("seconds", 0)))
                now = backend.now()
                return self._send(200, json.dumps({
                    "now": dt.datetime.fromtimestamp(now, dt.timezone.utc).isoformat(),
                    "days_ahead": round(backend.offset / 86400, 2)}))
            if url.path == "/dev/reference":
                item = backend.table.get_item(Key={"pk": f"PROB#{query.get('pid', '')}", "sk": "META"}).get("Item")
                return self._send(200 if item else 404, (item or {}).get("reference", ""),
                                  {"content-type": "text/plain; charset=utf-8"})
            if url.path == "/dev/state":
                rows = [i for i in backend.table.all_items() if i["pk"] == f"USER#{backend.user}"]
                return self._send(200, json.dumps(backend.api._plain(rows), ensure_ascii=False, indent=1))
            self._send(404, json.dumps({"error": f"no dev route {url.path}"}))

        def _handle(self):
            url = urlsplit(self.path)
            if url.path.startswith("/dev/"):
                return self._dev(url)
            length = int(self.headers.get("content-length") or 0)
            body = self.rfile.read(length).decode("utf-8", "replace") if length else None
            headers = {k.lower(): v for k, v in self.headers.items()}
            cookies = [c.strip() for c in headers.get("cookie", "").split(";") if c.strip()]
            # No sign-in on this machine: every request is the local user.
            headers["authorization"] = f"Bearer {backend.token()}"
            event = {"rawPath": url.path, "requestContext": {"http": {"method": self.command}},
                     "headers": headers, "cookies": cookies,
                     "queryStringParameters": dict(parse_qsl(url.query)) or None,
                     "body": body, "isBase64Encoded": False}
            resp = backend.api.lambda_handler(event, None)
            self._send(resp["statusCode"], resp.get("body") or "", resp.get("headers"), resp.get("cookies"))

        do_GET = do_POST = do_PUT = do_DELETE = _handle

    return Handler


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("corpus_root", type=Path)
    ap.add_argument("--port", type=int, default=8787)
    ap.add_argument("--user", default="dev")
    ap.add_argument("--solved", nargs="*", default=[], metavar="PID",
                    help="problems to start as solved, e.g. Amazon/B01")
    args = ap.parse_args()

    import ingest
    t0 = time.monotonic()
    items, skipped, _ = ingest.collect(args.corpus_root.expanduser())
    backend = Backend(user=args.user, background=True)
    backend.seed(items)
    by_pid = {it["pid"]: it for it in items}
    for pid in args.solved:
        if pid not in by_pid:
            sys.exit(f"--solved: unknown problem {pid}")
        seed_solved(backend, pid, by_pid[pid]["reference"])
    print(f"mogi dev API — {len(items)} problems loaded in {time.monotonic() - t0:.1f}s "
          f"({len(skipped)} skipped), signed in as @{args.user}")
    print(f"  http://127.0.0.1:{args.port}/api/home")
    print(f"  cd web && MOGI_SITE=http://127.0.0.1:{args.port} MOGI_CONFIG=/dev/null npm run dev")
    server = ThreadingHTTPServer(("127.0.0.1", args.port), make_handler(backend))  # this machine only
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
