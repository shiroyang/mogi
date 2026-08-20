"""mogi API — a single Lambda behind CloudFront `/api/*`.

Auth: GitHub OAuth (authorization-code flow) with a single-user allowlist; the
session is a stateless HS256 JWT in an HttpOnly cookie. The GitHub token from
login rides inside the session and is used to push accepted solutions to the
sync repo — unless the least-privilege `/mogi/sync-pat` parameter is set, in
which case login only asks for `read:user` and sync uses the PAT.

Stdlib + boto3 only, deliberately: the deploy artifact is the bare directory.
"""
from __future__ import annotations

import base64
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
    host = (event.get("headers") or {}).get("x-forwarded-host") \
        or (event.get("headers") or {}).get("host", "")
    return f"https://{host}"


def _session(event) -> dict | None:
    for c in event.get("cookies") or []:
        if c.startswith("mogi_session="):
            return jwt_decode(c.split("=", 1)[1])
    return None


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

    sess = _session(event)
    if not sess:
        return _resp(401, {"error": "not signed in"})
    user = sess["u"]

    if path == "/me":
        return _resp(200, {"login": user})
    if path == "/problems":
        return _resp(200, _problems(user))
    if path.startswith("/problems/"):
        return _resp(200, _problem(user, path.split("/")[2]))
    if path == "/submit" and method == "POST":
        if (event.get("headers") or {}).get("x-mogi") != "1":
            raise ApiError(403, "missing x-mogi header")
        return _resp(200, _submit(user, json.loads(event.get("body") or "{}")))
    if path.startswith("/submissions/"):
        _, _, prob, sk = path.split("/", 3)
        return _resp(200, _poll(user, sess, prob, urllib.parse.unquote(sk)))
    if path == "/activity":
        return _resp(200, _activity(user))
    raise ApiError(404, f"no route {method} {path}")


# ---------------------------------------------------------------- auth
def _login(event) -> dict:
    client_id = _param("github/client-id")
    scope = "read:user" if _param("sync-pat", required=False) else "repo"
    state = jwt_encode({"p": "state", "exp": time.time() + 600})
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
    session = jwt_encode({"u": login, "gh": access, "exp": time.time() + 30 * 86400})
    cookie = (f"mogi_session={session}; Path=/; HttpOnly; Secure; "
              f"SameSite=Lax; Max-Age={30 * 86400}")
    return _redirect("/", [cookie])


# ---------------------------------------------------------------- problems
def _problems(user: str) -> dict:
    probs = ddb.query(
        KeyConditionExpression="pk = :p",
        ExpressionAttributeValues={":p": "PROBLIST"},
    )["Items"]
    prog = ddb.query(
        KeyConditionExpression="pk = :p AND begins_with(sk, :s)",
        ExpressionAttributeValues={":p": f"USER#{user}", ":s": "PROG#"},
    )["Items"]
    by_id = {p["sk"].split("#", 1)[1]: p for p in prog}
    out = []
    for p in sorted(probs, key=lambda x: x["sk"]):
        pid = p["sk"]
        st = by_id.get(pid, {})
        out.append({"id": pid, "title": p.get("title", pid),
                    "corpus": p.get("corpus"), "tier": p.get("tier", ""),
                    "family": p.get("family", ""), "checks": p.get("checks", 0),
                    "status": st.get("status", ""), "attempts": st.get("attempts", 0),
                    "solved_at": st.get("solved_at")})
    solved = sum(1 for o in out if o["status"] == "solved")
    return {"problems": out, "solved": solved, "total": len(out)}


def _problem(user: str, prob_id: str) -> dict:
    meta = ddb.get_item(Key={"pk": f"PROB#{prob_id}", "sk": "META"}).get("Item")
    if not meta:
        raise ApiError(404, f"unknown problem {prob_id}")
    prog = ddb.get_item(Key={"pk": f"USER#{user}", "sk": f"PROG#{prob_id}"}).get("Item", {})
    solved = prog.get("status") == "solved"
    subs = ddb.query(
        KeyConditionExpression="pk = :p",
        ExpressionAttributeValues={":p": f"SUB#{prob_id}"},
        ScanIndexForward=False, Limit=15,
        ProjectionExpression="sk, verdict, passed, #tot, ms, #md, created, detail",
        ExpressionAttributeNames={"#tot": "total", "#md": "mode"},
    )["Items"]
    out = {
        "id": prob_id, "title": meta.get("title"), "corpus": meta.get("corpus"),
        "tier": meta.get("tier", ""), "family": meta.get("family", ""),
        "link": meta.get("link", ""), "statement": meta.get("statement", ""),
        "required": meta.get("required", []), "stub": meta.get("stub", ""),
        "checks": meta.get("checks", 0), "status": prog.get("status", ""),
        "attempts": prog.get("attempts", 0), "solved": solved,
        "submissions": subs,
    }
    if solved:  # spoilers unlock after the first AC
        out["analysis"] = meta.get("analysis", "")
        out["reference"] = meta.get("reference", "")
        out["tests"] = meta.get("harness", "")
    return out


# ---------------------------------------------------------------- judging
def _submit(user: str, body: dict) -> dict:
    prob = body.get("prob", "")
    code = body.get("code", "")
    mode = body.get("mode", "submit")
    if mode not in ("run", "submit"):
        raise ApiError(400, "mode must be run|submit")
    if not code.strip():
        raise ApiError(400, "empty submission")
    if len(code) > MAX_CODE:
        raise ApiError(400, f"submission over {MAX_CODE // 1000}KB")
    if not ddb.get_item(Key={"pk": f"PROB#{prob}", "sk": "META"}).get("Item"):
        raise ApiError(404, f"unknown problem {prob}")

    now_ms = int(time.time() * 1000)
    sk = f"{now_ms:013d}#{secrets.token_hex(3)}"
    item = {
        "pk": f"SUB#{prob}", "sk": sk, "user": user, "mode": mode,
        "code": code, "verdict": "PENDING", "created": int(time.time()),
        "gsi1pk": f"USER#{user}", "gsi1sk": sk, "prob": prob,
    }
    if mode == "run":
        item["expires"] = int(time.time()) + 3600  # DDB TTL sweeps practice runs
    ddb.put_item(Item=item)
    lam.invoke(FunctionName=JUDGE_FN, InvocationType="Event",
               Payload=json.dumps({"prob": prob, "sub_sk": sk, "user": user,
                                   "mode": mode, "code": code}).encode())
    return {"prob": prob, "sk": sk}


def _poll(user: str, sess: dict, prob: str, sk: str) -> dict:
    item = ddb.get_item(Key={"pk": f"SUB#{prob}", "sk": sk}).get("Item")
    if not item or item.get("user") != user:
        raise ApiError(404, "no such submission")
    out = {k: item.get(k) for k in
           ("sk", "verdict", "passed", "total", "ms", "detail", "stdout_tail",
            "trace", "mode", "created")}
    out["prob"] = prob
    try:
        out["cases"] = json.loads(item.get("cases_json") or "[]")
    except ValueError:
        out["cases"] = []
    if item.get("verdict") == "AC" and item.get("mode") == "submit":
        out["sync"] = _sync_if_needed(user, sess, prob, sk, item["code"], item)
    return out


# ---------------------------------------------------------------- github sync
def _sync_if_needed(user: str, sess: dict, prob: str, sk: str,
                    code: str, sub: dict) -> dict:
    prog = ddb.get_item(Key={"pk": f"USER#{user}", "sk": f"PROG#{prob}"}).get("Item", {})
    if prog.get("ac_sub") != sk:
        return {"state": "superseded"}
    if prog.get("synced_sub") == sk:
        return {"state": "done", "path": prog.get("synced_path")}

    token = _param("sync-pat", required=False) or sess.get("gh")
    if not token:
        return {"state": "skipped", "why": "no GitHub token in session"}
    repo = _param("sync-repo")
    meta = ddb.get_item(Key={"pk": f"PROB#{prob}", "sk": "META"},
                        ProjectionExpression="title, corpus, slug, link").get("Item", {})
    slug = meta.get("slug", prob)
    path = f"{meta.get('corpus', 'misc')}/{slug}.py"
    header = (f"# {prob} — {meta.get('title', '')}\n"
              f"# AC {sub.get('passed')}/{sub.get('total')} checks · "
              f"{sub.get('ms')} ms · judged by mogi\n"
              f"# Problem source: {meta.get('link', '')}\n\n")
    content = base64.b64encode((header + code).encode()).decode()

    url = f"https://api.github.com/repos/{repo}/contents/{urllib.parse.quote(path)}"
    auth = {"Authorization": f"Bearer {token}"}
    status, existing = _http(url, headers=auth)
    payload = {"message": f"AC {prob} — {meta.get('title', '')} "
                          f"({sub.get('passed')}/{sub.get('total')} checks, {sub.get('ms')} ms)",
               "content": content}
    if status == 200 and existing.get("sha"):
        payload["sha"] = existing["sha"]
    status, put = _http(url, data=payload, method="PUT", headers=auth)
    if status not in (200, 201):
        return {"state": "error",
                "why": f"GitHub {status}: {put.get('message', 'unknown')}"}
    ddb.update_item(
        Key={"pk": f"USER#{user}", "sk": f"PROG#{prob}"},
        UpdateExpression="SET synced_sub=:sk, synced_path=:p, synced_at=:t",
        ExpressionAttributeValues={":sk": sk, ":p": path, ":t": int(time.time())},
    )
    return {"state": "done", "path": path,
            "url": put.get("content", {}).get("html_url", "")}


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
                        "prob": i.get("prob"), "mode": i.get("mode"), "ms": i.get("ms")}
                       for i in items]}
