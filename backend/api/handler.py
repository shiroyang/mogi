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
import random
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
               "published", "round", "checks", "difficulty", "difficulty_src", "minutes", "loc",
               "classic", "classic_n")
# Hints. The first rung is free: clarifying questions are what you ask in the interview.
FREE_RUNG = "clarify"
# Reading the solution schedules a redo from a blank editor this many days later.
REDO_DAYS = 3
# The home page's "Today" pick stays short until this many problems are solved,
# and goes back to short after this many days without an accepted submission.
WARMUP_SOLVED = 3
IDLE_DAYS = 14
# The debrief asks how the solve went. A struggle comes back for a redo; a clean solve does not.
RATINGS = ("clean", "effort", "shaky")
RATING_REDO_DAYS = {"effort": 7, "shaky": 3}
NOTE_MAX = 1000
MAX_ELAPSED = 6 * 3600   # seconds on one problem; anything longer is a tab left open
# Question cards. One nobody has answered yet is due this many days after the solve.
# After that "knew it" climbs these intervals (days) and "not yet" goes back to the first.
NEW_CARD_DAYS = 3
CARD_INTERVALS = (1, 3, 7, 16, 35, 90)
REVIEW_BATCH = 12        # cards in one review sitting
# Mock rounds: unsolved problems, a clock, no hints.
# A problem tagged OA goes to the online assessment. The rest split by tier:
# Tier A is a design round, Tier B a coding round. `choices` are the lengths on offer, in minutes.
MOCK_FORMATS = {
    "coding": {"count": 1, "minutes": 45, "choices": (30, 45, 60)},
    "design": {"count": 1, "minutes": 60, "choices": (45, 60, 90)},
    "oa": {"count": 2, "minutes": 90, "choices": (60, 90, 120)},
}
OA_ROUNDS = ("OA", "OA/VO")
MOCK_TOP = 12            # a mock draws from this many of the best-ranked candidates
MOCK_HISTORY = 8         # earlier mocks listed on the mock page
_rng = random.SystemRandom()
# The companion: an egg you pick. It hatches and grows with what you solve.
# Only the choice is stored. XP, stage and mood are worked out from your progress each time,
# so they cannot drift, and what you solved before you picked the egg already counts.
EGGS = {"jelly": "classics", "shell": "amazon", "kelp": "google"}   # each egg comes with a path
EGG_NAMES = {"jelly": "Awa", "shell": "Tsubo", "kelp": "Mosu"}
PLANS = ("classics", "amazon", "google", "all")   # a path decides what Today draws from
HATCH_AT = 3                        # solved problems before the egg hatches
STAGE_XP = (200, 600, 1500, 3500)   # XP at which a hatched companion grows
GENRE_XP = 15                       # the first solve in a genre
REDO_XP = 5                         # each completed redo
REVIEW_XP = 1                       # each review answer
HINT_FIFTHS = 1                     # fifths of a problem's size that one hint costs
SLEEP_DAYS = 7                      # days without a run, a submission or a review before it sleeps
NAME_MAX = 24
_param_cache: dict[str, tuple[float, str | None]] = {}


def _now() -> int:
    """The clock for progress data. One place, so tests and the dev server can move it."""
    return int(time.time())


# ---------------------------------------------------------------- small utils
def _now_ms() -> int:
    """The same clock in milliseconds. It stamps submissions and mocks, so they sort by time."""
    return int(time.time() * 1000)


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


def _need_header(event) -> None:
    """Writes need the custom header. A cross-site form post cannot set it."""
    if (event.get("headers") or {}).get("x-mogi") != "1":
        raise ApiError(403, "missing x-mogi header")


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
        if len(parts) == 4 and parts[3] == "hint" and method == "POST":
            _need_header(event)
            return _resp(200, _hint(user, f"{parts[1]}/{parts[2]}", _body(event)))
        if len(parts) == 4 and parts[3] == "solution" and method == "POST":
            _need_header(event)
            return _resp(200, _solution(user, f"{parts[1]}/{parts[2]}"))
        if len(parts) == 4 and parts[3] == "debrief" and method == "POST":
            _need_header(event)
            return _resp(200, _debrief(user, f"{parts[1]}/{parts[2]}", _body(event)))
        if len(parts) == 4 and parts[3] == "card" and method == "POST":
            _need_header(event)
            return _resp(200, _grade_card(user, f"{parts[1]}/{parts[2]}", _body(event)))
    if path == "/review" and method == "GET":
        return _resp(200, _review(user))
    if path == "/companion":
        if method == "GET":
            return _resp(200, _companion(user))
        if method == "POST":
            _need_header(event)
            return _resp(200, _companion_set(user, _body(event)))
    if parts[:1] == ["mock"]:
        if len(parts) == 1 and method == "GET":
            return _resp(200, _mock_home(user))
        if len(parts) == 1 and method == "POST":
            _need_header(event)
            return _resp(200, _mock_start(user, _body(event)))
        if len(parts) == 2 and parts[1] == "end" and method == "POST":
            _need_header(event)
            return _resp(200, _mock_end(user))
        if len(parts) == 2 and method == "GET":
            return _resp(200, _mock_one(user, parts[1]))
    if path == "/submit" and method == "POST":
        _need_header(event)
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


def _rank_key(row: dict) -> tuple:
    """Sort key, best first. Every "what next" uses this one order, ties by pid."""
    return (-_rank_score(row), row["pid"])


def _minutes(row: dict) -> int:
    return int(row.get("minutes") or 30)


def _open_rows(rows: list[dict]) -> list[dict]:
    """Problems you can be sent to: not solved, and not waiting for a redo."""
    return [r for r in rows if r["status"] != "solved" and not r.get("redo_at")]


def _redo_why(prog: dict) -> str:
    """Why a redo is pending: you read the solution ("assisted"), or you rated the solve
    "effort" or "shaky". Rows from before ratings existed carry a date and no reason."""
    return prog.get("redo_why") or ("assisted" if prog.get("redo_at") else "")


def _problems(user: str, cards: bool = False) -> dict:
    """Every problem with your progress on it. `cards` adds each problem's card keys,
    which the review queue needs and the list page does not."""
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
            "hints": st.get("hints", 0), "redo_at": st.get("redo_at"),
            "redo_why": _redo_why(st), "redos": st.get("redos", 0),
        })
        if cards:
            row["card_keys"] = list(p.get("card_keys") or [])
        out.append(row)
    solved = sum(1 for o in out if o["status"] == "solved")
    genres = sorted({o["genre"] for o in out if o["genre"]}, key=str.lower)
    return {"problems": out, "solved": solved, "total": len(out), "genres": genres, "now": _now()}


def _next_unsolved(rows: list[dict], pid: str, genre: str) -> dict | None:
    """The best next rep: same genre first, then anything — by rank score."""
    cands = [r for r in _open_rows(rows) if r["pid"] != pid]
    same = [r for r in cands if r["genre"] == genre]
    pool = same or cands
    if not pool:
        return None
    best = min(pool, key=_rank_key)
    return {"pid": best["pid"], "id": best["id"], "title": best["title"],
            "same_genre": bool(same)}


def _ladder(meta: dict, prog: dict, unlocked: bool) -> list[dict]:
    """The hint rungs with their state. A body is only sent once its rung is open."""
    used = int(prog.get("hints") or 0)
    out, paid = [], 0
    for rung in meta.get("ladder") or []:
        free = rung["key"] == FREE_RUNG
        if free:
            is_open = unlocked or bool(prog.get("asked_at"))
        else:
            paid += 1
            is_open = unlocked or paid <= used
        item = {"key": rung["key"], "title": rung.get("title", ""), "free": free, "open": is_open}
        if is_open:
            item["body"] = rung.get("body", "")
        out.append(item)
    return out


def _problem(user: str, pid: str) -> dict:
    meta = ddb.get_item(Key={"pk": f"PROB#{pid}", "sk": "META"}).get("Item")
    if not meta:
        raise ApiError(404, f"unknown problem {pid}")
    prog = ddb.get_item(Key={"pk": f"USER#{user}", "sk": f"PROG#{pid}"}).get("Item", {})
    solved = prog.get("status") == "solved"
    # Reading the solution leaves a redo date on the row. Until that day the spoilers
    # stay open. On that day they close again, so the redo starts from a blank editor.
    redo_at = prog.get("redo_at")
    redo_due = bool(redo_at and redo_at <= _now())
    unlocked = (solved or bool(redo_at)) and not redo_due
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
        "difficulty": meta.get("difficulty", ""), "difficulty_src": meta.get("difficulty_src", ""),
        "minutes": meta.get("minutes", 0), "loc": meta.get("loc", 0),
        "published": meta.get("published", ""), "round": meta.get("round", ""),
        "link": meta.get("link", ""), "alt_link": meta.get("alt_link", ""),
        "statement": meta.get("statement", ""),
        "required": meta.get("required", []), "stub": meta.get("stub", ""),
        "checks": meta.get("checks", 0), "status": prog.get("status", ""),
        "attempts": prog.get("attempts", 0), "solved": solved,
        "priority": prog.get("priority", 0), "tags": list(prog.get("tags") or []),
        "submissions": subs,
        "ladder": _ladder(meta, prog, unlocked), "hints": int(prog.get("hints") or 0),
        "unlocked": unlocked, "assisted": _redo_why(prog) == "assisted", "redo_at": redo_at,
        "redo_why": _redo_why(prog),
        "redo_due": redo_due, "assisted_at": prog.get("assisted_at"), "redo_days": REDO_DAYS,
        "rating": prog.get("rating", ""), "rating_days": RATING_REDO_DAYS,
        "runs": prog.get("runs", 0), "solve_s": prog.get("solve_s"),
        "last_solve_s": prog.get("last_solve_s"),
        "now": _now(),
    }
    if unlocked:  # spoilers open after an AC, or once you chose to read the solution
        out["note"] = prog.get("note", "")     # your own note can give the trick away, so it follows the same rule
        if solved:  # the questions an interviewer asks next, with your schedule for each
            seen = _card_states(user, pid).get(pid, {})
            out["cards"] = [{**c, **_card_view(seen.get(c["key"]))} for c in meta.get("cards") or []]
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
    game = _game(user)
    if game.get("egg"):   # the companion, and what this problem has paid it
        states = _solved_states(user, listing["problems"])
        out["pet"] = _pet(listing["problems"], states, game)
        paid = _xp(listing["problems"], states)["per"].get(pid)
        out["xp"] = {**paid, "pending": False} if paid else {"xp": 0, "pending": bool(solved and redo_at)}
    mock = _mock_active(user)
    if mock and pid in mock[0]["pids"]:   # this problem is part of the mock that is running
        row, results = mock
        titles = {r["pid"]: r for r in listing["problems"]}
        i = row["pids"].index(pid)
        left = [p for j, p in enumerate(row["pids"]) if j != i and results[j]["ac_s"] is None]
        out["mock"] = {
            "id": row["sk"].split("#", 1)[1], "ends_at": int(row["ends_ms"]) // 1000,
            "index": i, "total": len(row["pids"]), "solved": results[i]["ac_s"] is not None,
            "next": ({"pid": left[0], "id": titles[left[0]]["id"], "title": titles[left[0]]["title"]}
                     if left and left[0] in titles else None),
        }
    return out


def _update_prog(user: str, pid: str, set_: dict | None = None, absent: dict | None = None,
                 add: dict | None = None, remove: tuple = ()) -> None:
    """One update of your progress row for a problem."""
    _update({"pk": f"USER#{user}", "sk": f"PROG#{pid}"}, set_, absent, add, remove)


def _update(key: dict, set_: dict | None = None, absent: dict | None = None,
            add: dict | None = None, remove: tuple = ()) -> None:
    """One update of one row. Every attribute is aliased and every alias is used,
    so DynamoDB cannot reject a reserved word or an unused placeholder.
    `absent` only writes when the attribute is missing. `add` increments a counter."""
    names: dict[str, str] = {}
    values: dict[str, object] = {}
    sets: list[str] = []

    def alias(attr: str) -> str:
        names[f"#{attr}"] = attr
        return f"#{attr}"

    for i, (attr, val) in enumerate((set_ or {}).items()):
        values[f":s{i}"] = val
        sets.append(f"{alias(attr)} = :s{i}")
    for i, (attr, val) in enumerate((absent or {}).items()):
        values[f":a{i}"] = val
        sets.append(f"{alias(attr)} = if_not_exists({alias(attr)}, :a{i})")
    for i, (attr, val) in enumerate((add or {}).items()):
        values[f":i{i}"] = val
        values[":zero"] = 0
        sets.append(f"{alias(attr)} = if_not_exists({alias(attr)}, :zero) + :i{i}")
    expr = ("SET " + ", ".join(sets) if sets else "")
    if remove:
        expr += " REMOVE " + ", ".join(alias(attr) for attr in remove)
    kw = {"ExpressionAttributeValues": values} if values else {}
    ddb.update_item(Key=key, UpdateExpression=expr.strip(), ExpressionAttributeNames=names, **kw)


def _hint(user: str, pid: str, body: dict) -> dict:
    """Open one hint rung. The free rung can be opened at any time.
    The others open in order, and how many you opened is kept on your progress row."""
    meta = ddb.get_item(Key={"pk": f"PROB#{pid}", "sk": "META"},
                        ProjectionExpression="#l", ExpressionAttributeNames={"#l": "ladder"}).get("Item")
    if meta is None:
        raise ApiError(404, f"unknown problem {pid}")
    keys = [r["key"] for r in meta.get("ladder") or []]
    key = str(body.get("key") or "")
    if key not in keys:
        raise ApiError(404, f"{pid} has no hint called '{key}'")
    if key != FREE_RUNG and _in_mock(user, pid):   # asking the interviewer is still allowed
        raise ApiError(409, "hints are off during a mock")
    prog = ddb.get_item(Key={"pk": f"USER#{user}", "sk": f"PROG#{pid}"}).get("Item", {})
    now = _now()
    if key == FREE_RUNG:
        if not prog.get("asked_at"):
            _update_prog(user, pid, set_={"asked_at": now, "last_at": now})
    else:
        step = [k for k in keys if k != FREE_RUNG].index(key) + 1
        used = int(prog.get("hints") or 0)
        if step > used + 1:
            raise ApiError(409, f"open hint {used + 1} first")
        if step == used + 1:
            _update_prog(user, pid, set_={"hints": step, "hint_at": now, "last_at": now})
    return _problem(user, pid)


def _solution(user: str, pid: str) -> dict:
    """Open the analysis, the reference and the tests before an accepted submission.
    The problem is marked as assisted and comes back for a redo REDO_DAYS later.
    Calling this again while a redo is due is a peek: it opens them and restarts the wait."""
    if not ddb.get_item(Key={"pk": f"PROB#{pid}", "sk": "META"},
                        ProjectionExpression="pk").get("Item"):
        raise ApiError(404, f"unknown problem {pid}")
    if _in_mock(user, pid):
        raise ApiError(409, "the solution is off during a mock")
    prog = ddb.get_item(Key={"pk": f"USER#{user}", "sk": f"PROG#{pid}"}).get("Item", {})
    now = _now()
    redo_at = prog.get("redo_at")
    already_open = (prog.get("status") == "solved" and not redo_at) or (redo_at and redo_at > now)
    if not already_open:
        _update_prog(user, pid, set_={"redo_at": now + REDO_DAYS * 86400, "redo_why": "assisted"},
                     absent={"assisted_at": now}, add={"peeks": 1})
    return _problem(user, pid)


def _debrief(user: str, pid: str, body: dict) -> dict:
    """Save what you say after an accepted solve: how it went, and a note for next time.
    "effort" and "shaky" bring the problem back for a redo. "clean" does not, and takes back
    a redo that an earlier rating set. A redo from reading the solution is left alone."""
    prog = ddb.get_item(Key={"pk": f"USER#{user}", "sk": f"PROG#{pid}"}).get("Item", {})
    if prog.get("status") != "solved":
        raise ApiError(409, "solve the problem first")
    now = _now()
    if prog.get("redo_at") and prog["redo_at"] <= now:
        raise ApiError(409, "the redo comes first")
    set_: dict = {}
    remove: list[str] = []
    if "rating" in body:
        rating = body.get("rating")
        if rating not in RATINGS:
            raise ApiError(400, f"rating must be one of {', '.join(RATINGS)}")
        set_.update(rating=rating, rated_at=now)
        if _redo_why(prog) != "assisted":
            if rating in RATING_REDO_DAYS:
                set_.update(redo_at=now + RATING_REDO_DAYS[rating] * 86400, redo_why=rating)
            elif prog.get("redo_at"):
                remove += ["redo_at", "redo_why"]
    if "note" in body:
        note = str(body.get("note") or "").strip()[:NOTE_MAX]
        if note:
            set_.update(note=note, note_at=now)
        else:
            remove += ["note", "note_at"]
    if not set_ and not remove:
        raise ApiError(400, "nothing to save: send rating and/or note")
    _update_prog(user, pid, set_=set_, remove=tuple(remove))
    return _problem(user, pid)


# ---------------------------------------------------------------- question cards
def _card_states(user: str, pid: str | None = None) -> dict[str, dict[str, dict]]:
    """Your review schedule: {pid: {card key: {due, ivl, reps, lapses, at}}}.
    One row per problem, one attribute per card, so a grade is a plain SET."""
    def cards(item: dict) -> dict[str, dict]:
        return {k[2:]: v for k, v in item.items() if k.startswith("c_")}
    if pid is not None:
        item = ddb.get_item(Key={"pk": f"USER#{user}", "sk": f"CARD#{pid}"}).get("Item") or {}
        return {pid: cards(item)}
    rows = _query_all(KeyConditionExpression="pk = :p AND begins_with(sk, :s)",
                      ExpressionAttributeValues={":p": f"USER#{user}", ":s": "CARD#"})
    return {r["sk"].split("#", 1)[1]: cards(r) for r in rows}


def _card_view(state: dict | None) -> dict:
    """What the app needs to know about one card's schedule. reps 0 = never answered."""
    state = state or {}
    return {"reps": state.get("reps", 0), "ivl": state.get("ivl", 0), "due": state.get("due")}


def _next_interval(prev: int | None, known: bool) -> int:
    """Days until a card comes back. "Knew it" climbs the intervals, "not yet" starts over."""
    if not known:
        return CARD_INTERVALS[0]
    if not prev:
        return CARD_INTERVALS[1]
    return next((d for d in CARD_INTERVALS if d > prev), CARD_INTERVALS[-1])


def _solved_states(user: str, rows: list[dict]) -> dict[str, dict[str, dict]]:
    """Your whole review schedule. Nothing is read until something is solved."""
    return _card_states(user) if any(r["status"] == "solved" for r in rows) else {}


def _due_cards(rows: list[dict], now: int, states: dict[str, dict[str, dict]]) -> list[tuple[int, str, int, str]]:
    """(due time, pid, position, key) for every card that is due, oldest first.
    A problem's cards count once it is solved. On its redo day they wait, because
    their answers would give the redo away. `rows` must come from _problems(cards=True)."""
    due = []
    for r in rows:
        keys = r.get("card_keys") or []
        if r["status"] != "solved" or not keys or (r.get("redo_at") and r["redo_at"] <= now):
            continue
        seen = states.get(r["pid"], {})
        fresh = int(r.get("solved_at") or 0) + NEW_CARD_DAYS * 86400
        for i, key in enumerate(keys):
            at = int(seen[key]["due"]) if key in seen else fresh
            if at <= now:
                due.append((at, r["pid"], i, key))
    return sorted(due)


def _review(user: str) -> dict:
    """One review sitting: the cards that are due, oldest first, with their text."""
    now = _now()
    rows = _problems(user, cards=True)["problems"]
    due = _due_cards(rows, now, _solved_states(user, rows))
    by_pid = {r["pid"]: r for r in rows}
    texts: dict[str, dict] = {}
    seen: dict[str, dict] = {}
    cards = []
    for at, pid, _i, key in due[:REVIEW_BATCH]:
        if pid not in texts:
            meta = ddb.get_item(Key={"pk": f"PROB#{pid}", "sk": "META"}, ProjectionExpression="#c",
                                ExpressionAttributeNames={"#c": "cards"}).get("Item") or {}
            texts[pid] = {c["key"]: c for c in meta.get("cards") or []}
            seen[pid] = _card_states(user, pid)[pid]
        if key in texts[pid]:
            cards.append({"pid": pid, "id": by_pid[pid]["id"], "title": by_pid[pid]["title"],
                          **texts[pid][key], **_card_view(seen[pid].get(key)), "due": at})
    return {"cards": cards, "due": len(due), "problems": len({d[1] for d in due}), "now": now}


def _grade_card(user: str, pid: str, body: dict) -> dict:
    """Record one answer: known or not. Returns the card's new schedule."""
    key, known = str(body.get("key") or ""), body.get("known")
    if not isinstance(known, bool):
        raise ApiError(400, "known must be true or false")
    meta = ddb.get_item(Key={"pk": f"PROB#{pid}", "sk": "META"}, ProjectionExpression="#c",
                        ExpressionAttributeNames={"#c": "cards"}).get("Item")
    if meta is None:
        raise ApiError(404, f"unknown problem {pid}")
    if key not in {c["key"] for c in meta.get("cards") or []}:
        raise ApiError(404, f"{pid} has no card '{key}'")
    prog = ddb.get_item(Key={"pk": f"USER#{user}", "sk": f"PROG#{pid}"}).get("Item", {})
    now = _now()
    if prog.get("status") != "solved":
        raise ApiError(409, "solve the problem first")
    if prog.get("redo_at") and prog["redo_at"] <= now:
        raise ApiError(409, "the redo comes first")
    old = _card_states(user, pid)[pid].get(key) or {}
    ivl = _next_interval(int(old["ivl"]) if old else None, known)
    state = {"due": now + ivl * 86400, "ivl": ivl, "reps": int(old.get("reps", 0)) + 1,
             "lapses": int(old.get("lapses", 0)) + (0 if known else 1), "at": now}
    ddb.update_item(Key={"pk": f"USER#{user}", "sk": f"CARD#{pid}"}, UpdateExpression="SET #c = :s",
                    ExpressionAttributeNames={"#c": f"c_{key}"}, ExpressionAttributeValues={":s": state})
    return {"pid": pid, "key": key, "known": known, **state, "now": now}


def _set_meta(user: str, pid: str, body: dict) -> dict:
    """Your own categorisation of a problem: genre override, 0–5 priority
    stars, free-form tags. Stored on the progress row; the corpus genre is kept
    separately so a reset is always possible."""
    if not ddb.get_item(Key={"pk": f"PROB#{pid}", "sk": "META"},
                        ProjectionExpression="pk").get("Item"):
        raise ApiError(404, f"unknown problem {pid}")
    sets, removes, values = [], [], {}
    # DynamoDB rejects aliases that the expression doesn't use, so only alias
    # the attributes this patch actually touches (a star click sends priority alone).
    names = {"#meta_at": "meta_at"}
    if "genre" in body:
        names["#genre"] = "genre"
    if "priority" in body:
        names["#priority"] = "priority"
    if "tags" in body:
        names["#tags"] = "tags"
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


# ---------------------------------------------------------------- the companion
def _game(user: str) -> dict:
    """The one stored row: which egg, which path, and its name."""
    return ddb.get_item(Key={"pk": f"USER#{user}", "sk": "GAME"}).get("Item") or {}


def _pays(row: dict) -> bool:
    """A solve pays once it is yours: solved, and not waiting on the redo of a solution you read."""
    return row["status"] == "solved" and not (row.get("redo_at") and row.get("redo_why") == "assisted")


def _xp(rows: list[dict], states: dict[str, dict[str, dict]]) -> dict:
    """All the XP there is, where it came from, and what each problem paid.

    A solved problem pays its size in minutes, less a fifth for each hint, plus 5 for each
    completed redo. The first solve in a genre adds 15. Each review answer adds 1."""
    per: dict[str, dict] = {}
    first: dict[str, dict] = {}   # genre → the row solved first in it
    for r in rows:
        if not _pays(r):
            continue
        size, hints, redos = _minutes(r), min(int(r.get("hints") or 0), 3), int(r.get("redos") or 0)
        per[r["pid"]] = {"xp": size * (5 - HINT_FIFTHS * hints) // 5 + REDO_XP * redos, "size": size,
                         "hints": hints, "redos": redos, "new_genre": False}
        genre = r["genre"]
        if genre and (genre not in first or (r.get("solved_at") or 0) < (first[genre].get("solved_at") or 0)):
            first[genre] = r
    for r in first.values():
        per[r["pid"]]["xp"] += GENRE_XP
        per[r["pid"]]["new_genre"] = True
    problems = sum(p["xp"] for p in per.values())
    reviews = REVIEW_XP * sum(int(c.get("reps") or 0) for cards in states.values() for c in cards.values())
    return {"total": problems + reviews, "problems": problems, "reviews": reviews, "per": per,
            "solved": len(per), "genres": len(first)}


def _plan_rows(rows: list[dict], plan: str) -> list[dict]:
    """The problems on a path."""
    if plan == "classics":
        return [r for r in rows if r.get("classic")]
    if plan in ("amazon", "google"):
        return [r for r in rows if (r.get("corpus") or "").lower() == plan]
    return rows


def _pet(rows: list[dict], states: dict[str, dict[str, dict]], game: dict) -> dict | None:
    """The companion in brief, or None when no egg is picked."""
    egg = game.get("egg")
    if egg not in EGGS:
        return None
    xp = _xp(rows, states)
    hatched = xp["solved"] >= HATCH_AT
    return {"egg": egg, "name": game.get("name") or EGG_NAMES[egg], "plan": game.get("plan") or EGGS[egg],
            "hatched": hatched, "to_hatch": max(0, HATCH_AT - xp["solved"]),
            "stage": 1 + sum(1 for t in STAGE_XP if xp["total"] >= t) if hatched else 0,
            "xp": xp["total"], "next_xp": next((t for t in STAGE_XP if xp["total"] < t), None) if hatched else None}


def _mood(pet: dict, due: int, last_active: int | None, now: int) -> str:
    """egg · asleep (a week with nothing done) · hungry (reviews are due) · awake. It never gets worse than asleep."""
    if not pet["hatched"]:
        return "egg"
    if last_active is None or now - last_active > SLEEP_DAYS * 86400:
        return "asleep"
    return "hungry" if due else "awake"


def _last_active(events: list[dict], states: dict[str, dict[str, dict]]) -> int | None:
    """When you last ran, submitted or answered a review, in epoch seconds."""
    seen = [e["ts"] // 1000 for e in events[:1]] + [int(c.get("at") or 0) for cards in states.values() for c in cards.values()]
    return max(seen) if seen else None


def _companion(user: str) -> dict:
    """The companion page: the choice, how it is doing, and where the XP came from."""
    now = _now()
    rows = _problems(user, cards=True)["problems"]
    states = _solved_states(user, rows)
    game = _game(user)
    xp = _xp(rows, states)
    pet = _pet(rows, states, game)
    due = len(_due_cards(rows, now, states))
    if pet:
        pet["mood"] = _mood(pet, due, _last_active(_activity(user)["events"], states), now)
    paid = sorted((r for r in rows if r["pid"] in xp["per"]), key=lambda r: (-(r.get("solved_at") or 0), r["pid"]))
    return {
        "pet": pet,
        "eggs": [{"key": k, "name": EGG_NAMES[k], "plan": plan} for k, plan in EGGS.items()],
        "plans": [{"key": k, "total": len(_plan_rows(rows, k)),
                   "solved": sum(1 for r in _plan_rows(rows, k) if r["status"] == "solved")} for k in PLANS],
        "plan": game.get("plan") or (EGGS[game["egg"]] if game.get("egg") in EGGS else "all"),
        "xp": {k: xp[k] for k in ("total", "problems", "reviews")},
        "solved": xp["solved"], "hatch_at": HATCH_AT, "stage_xp": list(STAGE_XP),
        "rules": {"genre_xp": GENRE_XP, "redo_xp": REDO_XP, "review_xp": REVIEW_XP, "sleep_days": SLEEP_DAYS},
        "genres": {"solved": xp["genres"], "total": len({r["genre"] for r in rows if r["genre"]})},
        "reviews_due": due,
        "recent": [{"pid": r["pid"], "id": r["id"], "title": r["title"], "genre": r["genre"],
                    "at": r.get("solved_at"), **xp["per"][r["pid"]]} for r in paid[:8]],
        # read the solution, so nothing yet: these pay when their redo is accepted
        "waiting": [{"pid": r["pid"], "id": r["id"], "title": r["title"], "redo_at": r["redo_at"]}
                    for r in rows if r["status"] == "solved" and not _pays(r)],
        "now": now,
    }


def _companion_set(user: str, body: dict) -> dict:
    """Pick an egg, change the path, rename it, or put it away (egg: "").
    Putting it away loses nothing: its XP comes from your progress, so it is all there when you pick again."""
    game = _game(user)
    set_: dict = {}
    remove: list[str] = []
    if "egg" in body:
        egg = body.get("egg") or ""
        if egg and egg not in EGGS:
            raise ApiError(400, f"egg must be one of {', '.join(EGGS)}")
        if egg:
            set_["egg"] = egg
            if "plan" not in body and not game.get("plan"):
                set_["plan"] = EGGS[egg]
        else:
            remove.append("egg")
    if "plan" in body:
        if body.get("plan") not in PLANS:
            raise ApiError(400, f"plan must be one of {', '.join(PLANS)}")
        set_["plan"] = body["plan"]
    if "name" in body:
        name = " ".join(str(body.get("name") or "").split())[:NAME_MAX]
        if name:
            set_["name"] = name
        else:
            remove.append("name")
    if not set_ and not remove:
        raise ApiError(400, "nothing to change: send egg, plan and/or name")
    _update({"pk": f"USER#{user}", "sk": "GAME"}, set_=set_, absent={"chosen_at": _now()} if set_.get("egg") else None,
            remove=tuple(remove))
    return _companion(user)


# ---------------------------------------------------------------- mock rounds
def _mock_format(row: dict) -> str:
    """Which mock a problem can be drawn for."""
    if row.get("round") in OA_ROUNDS:
        return "oa"
    return "design" if row.get("tier") == "A" else "coding"


def _mock_pools(rows: list[dict]) -> dict[str, dict[str, int]]:
    """How many problems each mock could draw from: {corpus: {format: count}}."""
    pools: dict[str, dict[str, int]] = {}
    for r in rows:
        pools.setdefault(r["corpus"], {f: 0 for f in MOCK_FORMATS})
    for r in _open_rows(rows):
        pools[r["corpus"]][_mock_format(r)] += 1
    return pools


def _mock_pick(pool: list[dict], count: int, rng) -> list[dict]:
    """Draw the problems for one mock. Problems you never touched come first.
    The draw is random among the best-ranked dozen, and avoids the same genre twice when it can."""
    touched = lambda r: bool(r["status"] or r.get("hints") or r.get("last_at"))  # noqa: E731
    picked: list[dict] = []
    for group in ([r for r in pool if not touched(r)], [r for r in pool if touched(r)]):
        top = sorted(group, key=_rank_key)[:MOCK_TOP]
        rng.shuffle(top)
        for same_genre_ok in (False, True):
            for r in top:
                if len(picked) == count:
                    return picked
                if r in picked or (not same_genre_ok and any(p["genre"] == r["genre"] for p in picked)):
                    continue
                picked.append(r)
    return picked


def _mock_rows(user: str, limit: int) -> list[dict]:
    """Your mocks, newest first."""
    return ddb.query(KeyConditionExpression="pk = :p AND begins_with(sk, :s)",
                     ExpressionAttributeValues={":p": f"USER#{user}", ":s": "MOCK#"},
                     ScanIndexForward=False, Limit=limit)["Items"]


def _mock_results(user: str, row: dict, now_ms: int) -> list[dict]:
    """For each problem of a mock: seconds from its start to the first accepted submission
    inside its window, or None. Read from the submissions, so a verdict that lands late still counts."""
    start = int(row["started_ms"])
    end = int(row.get("ended_ms") or min(now_ms, int(row["ends_ms"])))
    out = []
    for pid in row["pids"]:
        subs = _query_all(
            KeyConditionExpression="pk = :p AND sk BETWEEN :a AND :b",
            ExpressionAttributeValues={":p": f"SUB#{pid}", ":a": f"{start:013d}", ":b": f"{end:013d}~"},
            ProjectionExpression="sk, verdict, #md, #u",
            ExpressionAttributeNames={"#md": "mode", "#u": "user"},
        )
        accepted = [int(i["sk"][:13]) for i in subs
                    if i.get("user") == user and i.get("mode") == "submit" and i.get("verdict") == "AC"]
        out.append({"ac_ms": min(accepted) if accepted else None,
                    "ac_s": (min(accepted) - start) // 1000 if accepted else None})
    return out


def _mock_settle(user: str, row: dict) -> tuple[dict, list[dict]]:
    """(row, results), after ending the mock if every problem is solved or the time is up."""
    now_ms = _now_ms()
    results = _mock_results(user, row, now_ms)
    if not row.get("ended_ms"):
        if all(r["ac_ms"] is not None for r in results):
            ended, reason = max(r["ac_ms"] for r in results), "done"
        elif now_ms >= int(row["ends_ms"]):
            ended, reason = int(row["ends_ms"]), "time"
        else:
            return row, results
        _update({"pk": row["pk"], "sk": row["sk"]}, set_={"ended_ms": ended, "reason": reason})
        row = {**row, "ended_ms": ended, "reason": reason}
    return row, results


def _mock_active(user: str) -> tuple[dict, list[dict]] | None:
    """The mock that is running, with its results so far. None when no mock is running."""
    rows = _mock_rows(user, 1)
    if not rows:
        return None
    row, results = _mock_settle(user, rows[0])
    return None if row.get("ended_ms") else (row, results)


def _in_mock(user: str, pid: str) -> bool:
    mock = _mock_active(user)
    return bool(mock and pid in mock[0]["pids"])


def _mock_view(user: str, row: dict, titles: dict[str, dict]) -> dict:
    """One mock for the app. What kind of problem each one was is only said once the mock is over."""
    row, results = _mock_settle(user, row)
    active = not row.get("ended_ms")
    problems = []
    for i, pid in enumerate(row["pids"]):
        info = titles.get(pid, {})
        item = {"pid": pid, "id": info.get("id") or pid.split("/", 1)[-1], "title": info.get("title", ""),
                "ac_s": results[i]["ac_s"], "runs": row.get(f"r{i}", 0), "submits": row.get(f"s{i}", 0)}
        if not active:
            item.update({k: info.get(k) for k in ("genre", "difficulty", "minutes")})
        problems.append(item)
    ended = row.get("ended_ms")
    return {
        "id": row["sk"].split("#", 1)[1], "corpus": row.get("corpus", ""), "format": row.get("format", ""),
        "minutes": row.get("minutes", 0), "started_at": int(row["started_ms"]) // 1000,
        "ends_at": int(row["ends_ms"]) // 1000, "ended_at": int(ended) // 1000 if ended else None,
        "reason": row.get("reason", ""), "active": active,
        "solved": sum(1 for r in results if r["ac_s"] is not None), "total": len(row["pids"]),
        "problems": problems, "now": _now(),
    }


def _mock_home(user: str) -> dict:
    """The mock page: the one that is running, the earlier ones, and what can be started."""
    rows = _problems(user)["problems"]
    titles = {r["pid"]: r for r in rows}
    mocks = [_mock_view(user, m, titles) for m in _mock_rows(user, MOCK_HISTORY + 1)]
    return {
        "active": next((m for m in mocks if m["active"]), None),
        "history": [m for m in mocks if not m["active"]][:MOCK_HISTORY],
        "formats": {k: {"count": f["count"], "minutes": f["minutes"], "choices": list(f["choices"])}
                    for k, f in MOCK_FORMATS.items()},
        "pools": _mock_pools(rows), "now": _now(),
    }


def _mock_start(user: str, body: dict) -> dict:
    """Start a mock: draw the problems, start the clock."""
    corpus, fmt = str(body.get("corpus") or ""), str(body.get("format") or "")
    if fmt not in MOCK_FORMATS:
        raise ApiError(400, f"format must be one of {', '.join(MOCK_FORMATS)}")
    spec = MOCK_FORMATS[fmt]
    minutes = body.get("minutes", spec["minutes"])
    if isinstance(minutes, bool) or minutes not in spec["choices"]:
        raise ApiError(400, f"minutes must be one of {', '.join(map(str, spec['choices']))}")
    if _mock_active(user):
        raise ApiError(409, "a mock is already running")
    rows = _problems(user)["problems"]
    if not any(r["corpus"] == corpus for r in rows):
        raise ApiError(400, f"unknown corpus {corpus}")
    pool = [r for r in _open_rows(rows) if r["corpus"] == corpus and _mock_format(r) == fmt]
    if len(pool) < spec["count"]:
        raise ApiError(409, "not enough unsolved problems for this mock")
    start = _now_ms()
    row = {"pk": f"USER#{user}", "sk": f"MOCK#{start:013d}", "corpus": corpus, "format": fmt,
           "minutes": minutes, "pids": [r["pid"] for r in _mock_pick(pool, spec["count"], _rng)],
           "started_ms": start, "ends_ms": start + minutes * 60_000}
    ddb.put_item(Item=row)
    return _mock_view(user, row, {r["pid"]: r for r in rows})


def _mock_end(user: str) -> dict:
    """End the running mock now."""
    mock = _mock_active(user)
    if not mock:
        raise ApiError(409, "no mock is running")
    row = mock[0]
    _update({"pk": row["pk"], "sk": row["sk"]}, set_={"ended_ms": _now_ms(), "reason": "ended"})
    return _mock_one(user, row["sk"].split("#", 1)[1])


def _mock_one(user: str, mock_id: str) -> dict:
    row = ddb.get_item(Key={"pk": f"USER#{user}", "sk": f"MOCK#{mock_id}"}).get("Item")
    if not row:
        raise ApiError(404, "no such mock")
    return _mock_view(user, row, {r["pid"]: r for r in _problems(user)["problems"]})


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

    elapsed = body.get("elapsed_s")   # seconds the page's clock counted for this problem
    if elapsed is not None:
        try:
            elapsed = max(0, min(int(elapsed), MAX_ELAPSED))
        except (TypeError, ValueError):
            raise ApiError(400, "elapsed_s must be a number of seconds")

    now_ms = _now_ms()
    sk = f"{now_ms:013d}#{secrets.token_hex(3)}"
    item = {
        "pk": f"SUB#{pid}", "sk": sk, "user": user, "mode": mode,
        "code": code, "verdict": "PENDING", "created": now_ms // 1000,
        "gsi1pk": f"USER#{user}", "gsi1sk": sk, "prob": pid,
    }
    if mode == "run":
        item["expires"] = now_ms // 1000 + 3600  # DDB TTL sweeps practice runs
    if elapsed is not None:
        item["elapsed_s"] = elapsed
    ddb.put_item(Item=item)
    mock = _mock_active(user)
    if mock and pid in mock[0]["pids"]:   # a mock counts its runs and submits per problem
        counter = ("r" if mode == "run" else "s") + str(mock[0]["pids"].index(pid))
        _update({"pk": mock[0]["pk"], "sk": mock[0]["sk"]}, add={counter: 1})
    lam.invoke(FunctionName=JUDGE_FN, InvocationType="Event",
               Payload=json.dumps({"pid": pid, "sub_sk": sk, "user": user, "mode": mode,
                                   "code": code, "elapsed_s": elapsed}).encode())
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
                                  "status", "attempts", "last_at", "tier", "corpus",
                                  "difficulty", "difficulty_src", "minutes", "redo_at", "redo_why")}


def _daily(rows: list[dict], last_ac: int | None, now: int, scope: list[dict] | None = None) -> dict:
    """What the home page offers as "Today": the first item, plus a few alternates.

    A redo that is due comes first. Otherwise it is the best open problem that fits
    a time budget. The budget is 15 minutes while you are starting out or coming back
    after a break, and grows as problems get solved.
    `scope` narrows the pick to a path (the companion's). Redos and the budget look at everything."""
    due = sorted((r for r in rows if r.get("redo_at") and r["redo_at"] <= now),
                 key=lambda r: (r["redo_at"], r["pid"]))
    if due:
        return {"kind": "redo", "why": "redo", "budget": 0, "due": len(due),
                "items": [_slim(r) for r in due[:6]]}
    open_ = _open_rows(rows if scope is None else scope) or _open_rows(rows)
    solved = sum(1 for r in rows if r["status"] == "solved")
    if solved < WARMUP_SOLVED:
        budget, why = 15, "start"
    elif last_ac is None or now - last_ac > IDLE_DAYS * 86400:
        budget, why = 15, "back"
    else:
        budget, why = (30 if solved < 12 else 45), "ramp"
    pool: list[dict] = []
    for step in (15, 30, 45, 60):  # widen the budget until something fits
        if step >= budget:
            pool = [r for r in open_ if _minutes(r) <= step]
            if pool:
                budget = step
                break
    pool = sorted(pool or open_, key=_rank_key)
    return {"kind": "pick", "why": why, "budget": budget, "due": 0,
            "items": [_slim(r) for r in pool[:6]]}


def _home(user: str, hint: str = "") -> dict:
    """Everything the home page needs in one call: where you left off, what to do
    next, and the state of the campaign. `hint` is the pid the browser last had
    open (a local draft the server can't see); its row is returned so the page can
    prefer it over the server-side `last`."""
    listing = _problems(user, cards=True)
    rows = listing["problems"]
    now = _now()
    states = _solved_states(user, rows)
    due = _due_cards(rows, now, states)
    pet = _pet(rows, states, _game(user))
    # with a companion, Today and "highest ranked" draw from its path while the path has open problems
    scope = _plan_rows(rows, pet["plan"]) if pet else rows
    unsolved = _open_rows(rows)
    worked = [r for r in unsolved if r.get("last_at")]
    last = max(worked, key=lambda r: r["last_at"]) if worked else None
    ranked = _open_rows(scope) or unsolved
    pool = sorted((r for r in ranked if not last or r["pid"] != last["pid"]), key=_rank_key)
    nxt = pool[0] if pool else None
    next2 = pool[1] if len(pool) > 1 else None
    hint_row = next((r for r in rows if r["pid"] == hint), None) if hint else None

    events = _activity(user)["events"]
    accepted = [e["ts"] for e in events if e.get("verdict") == "AC" and e.get("mode") == "submit"]
    ac_days = sorted({dt.datetime.fromtimestamp(ts / 1000, dt.timezone.utc).date().isoformat()
                      for ts in accepted}, reverse=True)
    today = dt.datetime.fromtimestamp(now, dt.timezone.utc).date()
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
        "today": today.isoformat(), "now": now,
        "last": _slim(last), "next": _slim(nxt), "next2": _slim(next2), "hint": _slim(hint_row),
        "daily": _daily(rows, max(accepted) // 1000 if accepted else None, now, scope),
        "pet": {**pet, "mood": _mood(pet, len(due), _last_active(events, states), now)} if pet else None,
        "review": {"due": len(due), "problems": len({d[1] for d in due})},
        "mock": _mock_brief(user),
        "near": near, "top_genre": top_genre, "genres_total": len(by_genre),
        "genres_left": sum(1 for g in by_genre.values() if g["left"]),
        "events": events[:400],
    }


def _mock_brief(user: str) -> dict | None:
    """The running mock, for the home page: when it ends and how far along it is."""
    mock = _mock_active(user)
    if not mock:
        return None
    row, results = mock
    return {"id": row["sk"].split("#", 1)[1], "ends_at": int(row["ends_ms"]) // 1000,
            "solved": sum(1 for r in results if r["ac_s"] is not None), "total": len(row["pids"])}


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
