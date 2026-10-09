"""mogi API — a single Lambda behind CloudFront `/api/*`.

Auth: GitHub OAuth (authorization-code flow) with a single-user allowlist. The
session is a stateless HS256 JWT, carried either in an HttpOnly cookie (browser)
or as `Authorization: Bearer …` (the CLI and the VS Code extension, which obtain a
long-lived token through `/auth/cli`). The GitHub token from login rides inside the
session and is used to push accepted solutions to the sync repo — unless the
least-privilege `/mogi/sync-pat` parameter is set, in which case login only asks
for `read:user` and sync uses the PAT.

Problem ids are corpus-qualified — `Amazon/A16`, `Google/C07` — because the two
corpora reuse bare ids (`C07` exists in both). Routes take the two segments as-is:
`/problems/Amazon/A16`, `/submissions/Google/C07/<sk>`.

Stdlib + boto3 only, deliberately: the deploy artifact is the bare directory.
"""
from __future__ import annotations

import base64
import datetime as dt
import hashlib
import hmac
import json
import os
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
from decimal import Decimal

import boto3

TABLE = os.environ["TABLE"]
JUDGE_FN = os.environ["JUDGE_FN"]
PREFIX = os.environ.get("PARAM_PREFIX", "/mogi")

ddb = boto3.resource("dynamodb").Table(TABLE)
lam = boto3.client("lambda")
ssm = boto3.client("ssm")

MAX_CODE = 64_000
SESSION_DAYS = 30
CLI_TOKEN_DAYS = 365
# Slim per-problem fields copied from PROBLIST rows into the list response.
LIST_FIELDS = ("id", "title", "corpus", "tier", "genre", "family", "family_n", "rank",
               "pubs", "confidence", "importance", "practice_stars", "practice_url",
               "published", "round", "checks")
_param_cache: dict[str, tuple[float, str | None]] = {}


# ---------------------------------------------------------------- small utils
def _param(name: str, required: bool = True) -> str | None:
    now = time.time()
    hit = _param_cache.get(name)
    if hit and now - hit[0] < 300:
        val = hit[1]
    else:
        try:
            val = ssm.get_parameter(Name=f"{PREFIX}/{name}", WithDecryption=True)[
                "Parameter"]["Value"]
        except ssm.exceptions.ParameterNotFound:
            val = None
        _param_cache[name] = (now, val)
    if required and not val:
        raise ApiError(500, f"SSM parameter {PREFIX}/{name} is not set")
    return val


def _session_key() -> bytes:
    key = _param("session-key", required=False)
    if not key:
        key = secrets.token_hex(32)
        try:
            ssm.put_parameter(Name=f"{PREFIX}/session-key", Value=key,
                              Type="SecureString", Overwrite=False)
        except ssm.exceptions.ParameterAlreadyExists:
            key = ssm.get_parameter(Name=f"{PREFIX}/session-key",
                                    WithDecryption=True)["Parameter"]["Value"]
        _param_cache["session-key"] = (time.time(), key)
    return key.encode()


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def jwt_encode(payload: dict) -> str:
    head = _b64(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    body = _b64(json.dumps(payload).encode())
    sig = hmac.new(_session_key(), f"{head}.{body}".encode(), hashlib.sha256).digest()
    return f"{head}.{body}.{_b64(sig)}"


def jwt_decode(token: str) -> dict | None:
    try:
        head, body, sig = token.split(".")
        want = hmac.new(_session_key(), f"{head}.{body}".encode(), hashlib.sha256).digest()
        if not hmac.compare_digest(want, _unb64(sig)):
            return None
        payload = json.loads(_unb64(body))
        if payload.get("exp", 0) < time.time():
            return None
        return payload
    except Exception:
        return None


def _http(url: str, data: dict | None = None, headers: dict | None = None,
          method: str | None = None) -> tuple[int, dict]:
    req = urllib.request.Request(
        url,
        data=json.dumps(data).encode() if data is not None else None,
        headers={"Accept": "application/json", "User-Agent": "mogi-judge",
                 "Content-Type": "application/json", **(headers or {})},
        method=method or ("POST" if data is not None else "GET"),
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, json.loads(resp.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode() or "{}")
        except Exception:
            return e.code, {}


def _plain(obj):
    if isinstance(obj, Decimal):
        return int(obj) if obj == int(obj) else float(obj)
    if isinstance(obj, dict):
        return {k: _plain(v) for k, v in obj.items()}
    if isinstance(obj, (list, set, tuple)):
        return [_plain(v) for v in obj]
    return obj


def _query_all(**kw) -> list[dict]:
    """Query every page — the problem list is ~250 rows and must never truncate."""
    items: list[dict] = []
    start = None
    while True:
        if start:
            kw["ExclusiveStartKey"] = start
        page = ddb.query(**kw)
        items.extend(page["Items"])
        start = page.get("LastEvaluatedKey")
        if not start:
            return items


class ApiError(Exception):
    def __init__(self, status: int, msg: str):
        super().__init__(msg)
        self.status, self.msg = status, msg


# ---------------------------------------------------------------- http layer
def _resp(status: int, body, cookies: list[str] | None = None,
          headers: dict | None = None) -> dict:
    out = {
        "statusCode": status,
        "headers": {"content-type": "application/json",
                    "cache-control": "no-store", **(headers or {})},
        "body": json.dumps(_plain(body), ensure_ascii=False),
    }
    if cookies:
        out["cookies"] = cookies
    return out


def _redirect(url: str, cookies: list[str] | None = None) -> dict:
    out = {"statusCode": 302, "headers": {"location": url}, "body": ""}
    if cookies:
        out["cookies"] = cookies
    return out


def _origin(event) -> str:
    """The viewer-facing origin for OAuth redirects. CloudFront stashes the real
    host in x-forwarded-host; a front door that doesn't (e.g. a Vercel rewrite)
    can pin it with the optional /mogi/site-origin parameter."""
    override = _param("site-origin", required=False)
    if override:
        return override.rstrip("/")
    host = (event.get("headers") or {}).get("x-forwarded-host") \
        or (event.get("headers") or {}).get("host", "")
    return f"https://{host}"


def _session(event) -> dict | None:
    headers = event.get("headers") or {}
    auth = headers.get("authorization", "")
    if auth[:7].lower() == "bearer ":
        return jwt_decode(auth[7:].strip())
    for c in event.get("cookies") or []:
        if c.startswith("mogi_session="):
            return jwt_decode(c.split("=", 1)[1])
    return None


def _body(event) -> dict:
    raw = event.get("body") or ""
    if event.get("isBase64Encoded"):
        raw = base64.b64decode(raw).decode("utf-8", "replace")
    try:
        data = json.loads(raw or "{}")
    except ValueError:
        raise ApiError(400, "body is not JSON")
    if not isinstance(data, dict):
        raise ApiError(400, "body must be a JSON object")
    return data


def lambda_handler(event, _ctx):
    path = event.get("rawPath", "/")
    if path.startswith("/api"):
        path = path[4:] or "/"
    method = event["requestContext"]["http"]["method"]
    try:
        return _route(event, method, path)
    except ApiError as e:
        return _resp(e.status, {"error": e.msg})
    except Exception as e:  # surface, don't swallow — single-user tool
        return _resp(500, {"error": f"{type(e).__name__}: {e}"})


def _route(event, method: str, path: str) -> dict:
    if path == "/health":
        return _resp(200, {"ok": True})
    if path == "/auth/login":
        return _login(event)
    if path == "/auth/callback":
        return _callback(event)
    if path == "/auth/logout":
        return _redirect("/", ["mogi_session=; Path=/; Max-Age=0"])
    if path == "/auth/cli":
        return _cli_handoff(event)

    sess = _session(event)
    if not sess:
        return _resp(401, {"error": "not signed in"})
    user = sess["u"]
    parts = [p for p in path.split("/") if p]

    if path == "/me":
        return _resp(200, {
            "login": user, "cli": bool(sess.get("cli")),
            "can_sync": bool(sess.get("gh") or _param("sync-pat", required=False)),
        })
    if path == "/home":
        hint = (event.get("queryStringParameters") or {}).get("hint", "")
        return _resp(200, _home(user, hint))
    if parts[:1] == ["problems"]:
        if len(parts) == 1 and method == "GET":
            return _resp(200, _problems(user))
        if len(parts) == 3 and method == "GET":
            return _resp(200, _problem(user, f"{parts[1]}/{parts[2]}"))
        if len(parts) == 4 and parts[3] == "meta" and method in ("PUT", "POST"):
            return _resp(200, _set_meta(user, f"{parts[1]}/{parts[2]}", _body(event)))
    if path == "/submit" and method == "POST":
        if (event.get("headers") or {}).get("x-mogi") != "1":
            raise ApiError(403, "missing x-mogi header")
        return _resp(200, _submit(user, _body(event)))
    if parts[:1] == ["submissions"] and len(parts) == 4:
        return _resp(200, _poll(user, sess, f"{parts[1]}/{parts[2]}",
                                urllib.parse.unquote(parts[3])))
    if path == "/activity":
        return _resp(200, _activity(user))
    raise ApiError(404, f"no route {method} {path}")


# ---------------------------------------------------------------- auth
def _safe_next(value: str | None) -> str:
    """Only same-origin paths may be used as a post-login destination."""
    if not value or not value.startswith("/") or value.startswith("//"):
        return "/"
    return value[:400]


def _login(event) -> dict:
    client_id = _param("github/client-id")
    scope = "read:user" if _param("sync-pat", required=False) else "repo"
    nxt = _safe_next((event.get("queryStringParameters") or {}).get("next"))
    state = jwt_encode({"p": "state", "next": nxt, "exp": time.time() + 600})
    q = urllib.parse.urlencode({
        "client_id": client_id,
        "redirect_uri": f"{_origin(event)}/api/auth/callback",
        "scope": scope,
        "state": state,
    })
    return _redirect(f"https://github.com/login/oauth/authorize?{q}")


def _callback(event) -> dict:
    qs = event.get("queryStringParameters") or {}
    state = jwt_decode(qs.get("state", ""))
    if not state or state.get("p") != "state":
        raise ApiError(403, "bad OAuth state")
    status, tok = _http("https://github.com/login/oauth/access_token", data={
        "client_id": _param("github/client-id"),
        "client_secret": _param("github/client-secret"),
        "code": qs.get("code", ""),
    })
    access = tok.get("access_token")
    if status != 200 or not access:
        raise ApiError(403, f"token exchange failed: {tok.get('error_description', status)}")
    status, gh_user = _http("https://api.github.com/user",
                            headers={"Authorization": f"Bearer {access}"})
    login = gh_user.get("login", "")
    allowed = _param("allowed-github-login")
    if login.lower() != allowed.lower():
        raise ApiError(403, f"GitHub user @{login} is not allowed on this judge")
    session = jwt_encode({"u": login, "gh": access, "exp": time.time() + SESSION_DAYS * 86400})
    cookie = (f"mogi_session={session}; Path=/; HttpOnly; Secure; "
              f"SameSite=Lax; Max-Age={SESSION_DAYS * 86400}")
    return _redirect(_safe_next(state.get("next")), [cookie])


def _cli_handoff(event) -> dict:
    """Hand a long-lived bearer token to a local client (CLI / VS Code).

    The client listens on 127.0.0.1:<port> and opens this URL in the browser. If
    the browser has no session yet we bounce through GitHub login and come back
    here. The token travels in the URL *fragment*, which browsers never send to a
    server, so it does not appear in request logs; the local listener's page reads
    it from `location.hash` and posts it to itself.
    """
    qs = event.get("queryStringParameters") or {}
    try:
        port = int(qs.get("port", ""))
    except ValueError:
        raise ApiError(400, "port is required")
    if not 1024 <= port <= 65535:
        raise ApiError(400, "port out of range")
    state = qs.get("state", "")[:64]
    sess = _session(event)
    if not sess:
        here = "/api/auth/cli?" + urllib.parse.urlencode({"port": port, "state": state})
        return _redirect("/api/auth/login?" + urllib.parse.urlencode({"next": here}))
    payload = {"u": sess["u"], "cli": True, "exp": time.time() + CLI_TOKEN_DAYS * 86400}
    if sess.get("gh") and not _param("sync-pat", required=False):
        payload["gh"] = sess["gh"]  # needed for AC sync unless a PAT is configured
    frag = urllib.parse.urlencode({"token": jwt_encode(payload), "state": state,
                                   "login": sess["u"]})
    return _redirect(f"http://127.0.0.1:{port}/callback#{frag}")


# ---------------------------------------------------------------- problems
def _rank_score(row: dict) -> int:
    """Your own priority stars outrank the computed importance; ties by score."""
    return int(row.get("priority") or 0) * 1000 + int(row.get("importance") or 0)


def _problems(user: str) -> dict:
    probs = _query_all(
        KeyConditionExpression="pk = :p",
        ExpressionAttributeValues={":p": "PROBLIST"},
    )
    prog = _query_all(
        KeyConditionExpression="pk = :p AND begins_with(sk, :s)",
        ExpressionAttributeValues={":p": f"USER#{user}", ":s": "PROG#"},
    )
    by_pid = {p["sk"].split("#", 1)[1]: p for p in prog}
    out = []
    for p in sorted(probs, key=lambda x: x["sk"]):
        pid = p["sk"]
        st = by_pid.get(pid, {})
        row = {"pid": pid, **{k: p.get(k) for k in LIST_FIELDS}}
        row["id"] = p.get("id") or pid.split("/", 1)[-1]
        row["genre_corpus"] = p.get("genre") or p.get("family") or ""
        row["genre"] = st.get("genre") or row["genre_corpus"]
        row.update({
            "status": st.get("status", ""), "attempts": st.get("attempts", 0),
            "solved_at": st.get("solved_at"), "last_at": st.get("last_at"),
            "priority": st.get("priority", 0), "tags": list(st.get("tags") or []),
        })
        out.append(row)
    solved = sum(1 for o in out if o["status"] == "solved")
    genres = sorted({o["genre"] for o in out if o["genre"]}, key=str.lower)
    return {"problems": out, "solved": solved, "total": len(out), "genres": genres}


def _next_unsolved(rows: list[dict], pid: str, genre: str) -> dict | None:
    """The best next rep: same genre first, then anything — by rank score."""
    cands = [r for r in rows if r["pid"] != pid and r["status"] != "solved"]
    same = [r for r in cands if r["genre"] == genre]
    pool = same or cands
    if not pool:
        return None
    best = max(pool, key=lambda r: (_rank_score(r), r["pid"]))
    return {"pid": best["pid"], "id": best["id"], "title": best["title"],
            "same_genre": bool(same)}


def _problem(user: str, pid: str) -> dict:
    meta = ddb.get_item(Key={"pk": f"PROB#{pid}", "sk": "META"}).get("Item")
    if not meta:
        raise ApiError(404, f"unknown problem {pid}")
    prog = ddb.get_item(Key={"pk": f"USER#{user}", "sk": f"PROG#{pid}"}).get("Item", {})
    solved = prog.get("status") == "solved"
    subs = ddb.query(
        KeyConditionExpression="pk = :p",
        ExpressionAttributeValues={":p": f"SUB#{pid}"},
        ScanIndexForward=False, Limit=15,
        ProjectionExpression="sk, verdict, passed, #tot, ms, #md, created, detail",
        ExpressionAttributeNames={"#tot": "total", "#md": "mode"},
    )["Items"]
    genre_corpus = meta.get("genre") or meta.get("family", "")
    out = {
        "pid": pid, "id": meta.get("id") or pid.split("/", 1)[-1],
        "slug": meta.get("slug", ""),
        "title": meta.get("title"), "corpus": meta.get("corpus"),
        "tier": meta.get("tier", ""), "family": meta.get("family", ""),
        "genre": prog.get("genre") or genre_corpus, "genre_corpus": genre_corpus,
        "family_n": meta.get("family_n", 0), "rank": meta.get("rank"),
        "pubs": meta.get("pubs", 1), "confidence": meta.get("confidence", 0),
        "importance": meta.get("importance", 0), "practice": meta.get("practice") or {},
        "published": meta.get("published", ""), "round": meta.get("round", ""),
        "link": meta.get("link", ""), "alt_link": meta.get("alt_link", ""),
        "statement": meta.get("statement", ""),
        "required": meta.get("required", []), "stub": meta.get("stub", ""),
        "checks": meta.get("checks", 0), "status": prog.get("status", ""),
        "attempts": prog.get("attempts", 0), "solved": solved,
        "priority": prog.get("priority", 0), "tags": list(prog.get("tags") or []),
        "submissions": subs,
    }
    if solved:  # spoilers unlock after the first AC
        out["analysis"] = meta.get("analysis", "")
        out["reference"] = meta.get("reference", "")
        out["tests"] = meta.get("harness", "")
        if prog.get("ac_sub"):
            sub = ddb.get_item(Key={"pk": f"SUB#{pid}", "sk": prog["ac_sub"]},
                               ProjectionExpression="#c",
                               ExpressionAttributeNames={"#c": "code"}).get("Item", {})
            out["ac_code"] = sub.get("code", "")
    listing = _problems(user)
    out["next"] = _next_unsolved(listing["problems"], pid, out["genre"])
    out["genres"] = listing["genres"]
    return out


def _set_meta(user: str, pid: str, body: dict) -> dict:
    """Your own categorisation of a problem: genre override, 0–5 priority
    stars, free-form tags. Stored on the progress row; the corpus genre is kept
    separately so a reset is always possible."""
    if not ddb.get_item(Key={"pk": f"PROB#{pid}", "sk": "META"},
                        ProjectionExpression="pk").get("Item"):
        raise ApiError(404, f"unknown problem {pid}")
    sets, removes, values = [], [], {}
    names = {"#genre": "genre", "#priority": "priority", "#tags": "tags", "#meta_at": "meta_at"}
    if "genre" in body:
        genre = str(body.get("genre") or "").strip()[:60]
        if genre:
            sets.append("#genre = :g")
            values[":g"] = genre
        else:
            removes.append("#genre")
    if "priority" in body:
        raw = body.get("priority")
        try:
            prio = int(raw) if raw not in (None, "") else 0
        except (TypeError, ValueError):
            raise ApiError(400, "priority must be an integer 0–5")
        if not 0 <= prio <= 5:
            raise ApiError(400, "priority must be 0–5")
        if prio:
            sets.append("#priority = :pr")
            values[":pr"] = prio
        else:
            removes.append("#priority")
    if "tags" in body:
        tags = body.get("tags") or []
        if isinstance(tags, str):
            tags = tags.split(",")
        if not isinstance(tags, list):
            raise ApiError(400, "tags must be a list or a comma-separated string")
        clean = sorted({str(t).strip()[:30] for t in tags if str(t).strip()},
                       key=str.lower)[:20]
        if clean:
            sets.append("#tags = :t")
            values[":t"] = clean
        else:
            removes.append("#tags")
    if not sets and not removes:
        raise ApiError(400, "nothing to update: send genre, priority and/or tags")
    sets.append("#meta_at = :now")
    values[":now"] = int(time.time())
    expr = "SET " + ", ".join(sets) + (" REMOVE " + ", ".join(removes) if removes else "")
    item = ddb.update_item(
        Key={"pk": f"USER#{user}", "sk": f"PROG#{pid}"},
        UpdateExpression=expr, ExpressionAttributeNames=names,
        ExpressionAttributeValues=values, ReturnValues="ALL_NEW",
    )["Attributes"]
    meta = ddb.get_item(Key={"pk": f"PROB#{pid}", "sk": "META"},
                        ProjectionExpression="#g, #f",  # `family` is a DDB reserved word
                        ExpressionAttributeNames={"#g": "genre", "#f": "family"}).get("Item", {})
    genre_corpus = meta.get("genre") or meta.get("family", "")
    return {"pid": pid, "genre": item.get("genre") or genre_corpus,
            "genre_corpus": genre_corpus, "priority": item.get("priority", 0),
            "tags": list(item.get("tags") or [])}


# ---------------------------------------------------------------- judging
def _submit(user: str, body: dict) -> dict:
    pid = body.get("pid") or body.get("prob") or ""
    code = body.get("code", "")
    mode = body.get("mode", "submit")
    if mode not in ("run", "submit"):
        raise ApiError(400, "mode must be run|submit")
    if not isinstance(code, str) or not code.strip():
        raise ApiError(400, "empty submission")
    if len(code) > MAX_CODE:
        raise ApiError(400, f"submission over {MAX_CODE // 1000}KB")
    if not ddb.get_item(Key={"pk": f"PROB#{pid}", "sk": "META"},
                        ProjectionExpression="pk").get("Item"):
        raise ApiError(404, f"unknown problem {pid}")

    now_ms = int(time.time() * 1000)
    sk = f"{now_ms:013d}#{secrets.token_hex(3)}"
    item = {
        "pk": f"SUB#{pid}", "sk": sk, "user": user, "mode": mode,
        "code": code, "verdict": "PENDING", "created": int(time.time()),
        "gsi1pk": f"USER#{user}", "gsi1sk": sk, "prob": pid,
    }
    if mode == "run":
        item["expires"] = int(time.time()) + 3600  # DDB TTL sweeps practice runs
    ddb.put_item(Item=item)
    lam.invoke(FunctionName=JUDGE_FN, InvocationType="Event",
               Payload=json.dumps({"pid": pid, "sub_sk": sk, "user": user,
                                   "mode": mode, "code": code}).encode())
    return {"pid": pid, "sk": sk}


def _poll(user: str, sess: dict, pid: str, sk: str) -> dict:
    item = ddb.get_item(Key={"pk": f"SUB#{pid}", "sk": sk}).get("Item")
    if not item or item.get("user") != user:
        raise ApiError(404, "no such submission")
    out = {k: item.get(k) for k in
           ("sk", "verdict", "passed", "total", "ms", "detail", "stdout_tail",
            "trace", "mode", "created")}
    out["pid"] = pid
    try:
        out["cases"] = json.loads(item.get("cases_json") or "[]")
    except ValueError:
        out["cases"] = []
    if item.get("verdict") == "AC" and item.get("mode") == "submit":
        out["sync"] = _sync_if_needed(user, sess, pid, sk, item["code"], item)
    return out


# ---------------------------------------------------------------- github sync
def _sync_if_needed(user: str, sess: dict, pid: str, sk: str,
                    code: str, sub: dict) -> dict:
    prog = ddb.get_item(Key={"pk": f"USER#{user}", "sk": f"PROG#{pid}"}).get("Item", {})
    if prog.get("ac_sub") != sk:
        return {"state": "superseded"}
    if prog.get("synced_sub") == sk:
        return {"state": "done", "path": prog.get("synced_path")}

    token = _param("sync-pat", required=False) or sess.get("gh")
    if not token:
        return {"state": "skipped", "why": "no GitHub token in session — sign in again "
                                           "or set /mogi/sync-pat"}
    repo = _param("sync-repo")
    meta = ddb.get_item(Key={"pk": f"PROB#{pid}", "sk": "META"},
                        ProjectionExpression="title, corpus, slug, link").get("Item", {})
    slug = meta.get("slug", pid.replace("/", "_"))
    path = f"{meta.get('corpus', 'misc')}/{slug}.py"
    header = (f"# {pid} — {meta.get('title', '')}\n"
              f"# AC {sub.get('passed')}/{sub.get('total')} checks · "
              f"{sub.get('ms')} ms · judged by mogi\n"
              f"# Problem source: {meta.get('link', '')}\n\n")
    content = base64.b64encode((header + code).encode()).decode()

    url = f"https://api.github.com/repos/{repo}/contents/{urllib.parse.quote(path)}"
    auth = {"Authorization": f"Bearer {token}"}
    status, existing = _http(url, headers=auth)
    payload = {"message": f"AC {pid} — {meta.get('title', '')} "
                          f"({sub.get('passed')}/{sub.get('total')} checks, {sub.get('ms')} ms)",
               "content": content}
    if status == 200 and existing.get("sha"):
        payload["sha"] = existing["sha"]
    status, put = _http(url, data=payload, method="PUT", headers=auth)
    if status not in (200, 201):
        return {"state": "error",
                "why": f"GitHub {status}: {put.get('message', 'unknown')}"}
    ddb.update_item(
        Key={"pk": f"USER#{user}", "sk": f"PROG#{pid}"},
        UpdateExpression="SET synced_sub=:sk, synced_path=:p, synced_at=:t",
        ExpressionAttributeValues={":sk": sk, ":p": path, ":t": int(time.time())},
    )
    return {"state": "done", "path": path,
            "url": put.get("content", {}).get("html_url", "")}


# ---------------------------------------------------------------- home
def _slim(r: dict | None) -> dict | None:
    if not r:
        return None
    return {k: r.get(k) for k in ("pid", "id", "title", "genre", "importance", "priority",
                                  "status", "attempts", "last_at", "tier", "corpus")}


def _home(user: str, hint: str = "") -> dict:
    """Everything the home page needs in one call: where you left off, what to do
    next, and the state of the campaign. `hint` is the pid the browser last had
    open (a local draft the server can't see); its row is returned so the page can
    prefer it over the server-side `last`."""
    listing = _problems(user)
    rows = listing["problems"]
    unsolved = [r for r in rows if r["status"] != "solved"]
    worked = [r for r in unsolved if r.get("last_at")]
    last = max(worked, key=lambda r: r["last_at"]) if worked else None
    pool = sorted((r for r in unsolved if not last or r["pid"] != last["pid"]),
                  key=lambda r: (-_rank_score(r), r["pid"]))
    nxt = pool[0] if pool else None
    next2 = pool[1] if len(pool) > 1 else None
    hint_row = next((r for r in rows if r["pid"] == hint), None) if hint else None

    events = _activity(user)["events"]
    ac_days = sorted({dt.datetime.fromtimestamp(e["ts"] / 1000, dt.timezone.utc).date().isoformat()
                      for e in events if e.get("verdict") == "AC" and e.get("mode") == "submit"},
                     reverse=True)
    today = dt.datetime.now(dt.timezone.utc).date()
    streak, cursor = 0, today
    day_set = set(ac_days)
    if cursor.isoformat() not in day_set:  # a streak may still be alive from yesterday
        cursor -= dt.timedelta(days=1)
    while cursor.isoformat() in day_set:
        streak += 1
        cursor -= dt.timedelta(days=1)

    by_genre: dict[str, dict] = {}
    for r in rows:
        g = by_genre.setdefault(r["genre"] or "—", {"genre": r["genre"] or "—", "solved": 0, "left": 0, "top": 0})
        g["solved" if r["status"] == "solved" else "left"] += 1
        g["top"] = max(g["top"], int(r.get("importance") or 0))
    started = [g for g in by_genre.values() if g["solved"] and g["left"]]
    near = min(started, key=lambda g: (g["left"], -g["top"])) if started else None
    top_genre = max(by_genre.values(), key=lambda g: (g["top"], -g["left"])) if by_genre else None
    return {
        "login": user, "solved": listing["solved"], "total": listing["total"],
        "streak": streak, "last_ac_day": ac_days[0] if ac_days else None,
        "today": today.isoformat(),
        "last": _slim(last), "next": _slim(nxt), "next2": _slim(next2), "hint": _slim(hint_row),
        "near": near, "top_genre": top_genre, "genres_total": len(by_genre),
        "genres_left": sum(1 for g in by_genre.values() if g["left"]),
        "events": events[:400],
    }


# ---------------------------------------------------------------- activity
def _activity(user: str) -> dict:
    items = ddb.query(
        IndexName="gsi1",
        KeyConditionExpression="gsi1pk = :p",
        ExpressionAttributeValues={":p": f"USER#{user}"},
        ScanIndexForward=False, Limit=400,
        ProjectionExpression="gsi1sk, verdict, prob, #md, ms",
        ExpressionAttributeNames={"#md": "mode"},
    )["Items"]
    return {"events": [{"ts": int(i["gsi1sk"].split("#")[0]), "verdict": i.get("verdict"),
                        "pid": i.get("prob"), "mode": i.get("mode"), "ms": i.get("ms")}
                       for i in items]}
