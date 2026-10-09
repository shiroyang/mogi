"""mogi — command-line client for the 真題 online judge.

    mogi login                      sign in once (browser hand-off; token saved locally)
    mogi ls [--genre G] [--sort importance|frequency|…] [--status fresh]
    mogi open A16 [--code]          materialise ~/mogi/Amazon/A16_…/{problem.md,solution.py}
    mogi run   [ID|PATH]            judge solution.py against the problem's own tests
    mogi submit [ID|PATH]           same, but counts — AC unlocks spoilers and syncs to GitHub
    mogi tag A16 --genre graph --priority 5 --tags redo,weak
    mogi pick [--genre G] [--open]  the most important unsolved problem
    mogi stats · mogi whoami · mogi web [ID] · mogi config [key [value]]

Exit codes: 0 = AC (or success), 1 = any other verdict, 2 = error.
"""
from __future__ import annotations

import argparse
import json
import random
import shutil
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

from . import __version__, config, render, workspace
from .api import Api, ApiError

SORTS = {
    "importance": lambda p: (-rank_score(p), p["pid"]),
    "frequency": lambda p: (-(p.get("pubs") or 0), -(p.get("family_n") or 0), -rank_score(p)),
    "genre": lambda p: ((p.get("genre") or "").lower(), -rank_score(p)),
    "tier": lambda p: (p.get("tier") or "", -rank_score(p)),
    "recent": lambda p: (-(p.get("last_at") or 0), -rank_score(p)),
    "attempts": lambda p: (-(p.get("attempts") or 0), -rank_score(p)),
    "id": lambda p: p["pid"],
}


def rank_score(p: dict) -> int:
    return int(p.get("priority") or 0) * 1000 + int(p.get("importance") or 0)


class Ctx:
    def __init__(self, args):
        self.args = args
        self.cfg = config.load()
        if getattr(args, "site", None):
            self.cfg["site"] = args.site
        self.api = Api(self.cfg["site"], self.cfg.get("token"))
        self.color = render.use_color() and not getattr(args, "no_color", False)
        self._problems: list[dict] | None = None

    @property
    def ws(self) -> Path:
        return config.workspace(self.cfg)

    def problems(self) -> list[dict]:
        if self._problems is None:
            self._problems = self.api.problems()["problems"]
        return self._problems

    def resolve(self, token: str) -> dict:
        """A pid (`Amazon/A16`), a bare id (`A16`, case-insensitive) or a path."""
        rows = self.problems()
        if "/" in token and not Path(token).exists():
            hit = next((p for p in rows if p["pid"].lower() == token.lower()), None)
            if not hit:
                raise ApiError(404, f"unknown problem {token}")
            return hit
        if Path(token).exists():
            found = workspace.find_marker(Path(token))
            if not found:
                raise ApiError(404, f"{token} is not inside a mogi problem directory (no .mogi.json)")
            return self.resolve(found[1]["pid"])
        hits = [p for p in rows if p["id"].lower() == token.lower()]
        if len(hits) == 1:
            return hits[0]
        if not hits:
            raise ApiError(404, f"unknown problem {token} — try `mogi ls -q {token}`")
        raise ApiError(409, f"{token} exists in both corpora — say which: "
                            + " or ".join(h["pid"] for h in hits))

    def current(self, token: str | None) -> tuple[dict, Path | None]:
        """(problem row, local directory or None) for an optional argument."""
        if token:
            row = self.resolve(token)
            d = workspace.find_marker(Path(token))[0] if Path(token).exists() \
                else workspace.dir_for_pid(self.ws, row["pid"])
            return row, d
        found = workspace.find_marker(Path.cwd())
        if not found:
            raise ApiError(2, "not inside a problem directory — pass an id, e.g. `mogi run A16`")
        return self.resolve(found[1]["pid"]), found[0]


# ------------------------------------------------------------------ commands
def cmd_login(ctx: Ctx) -> int:
    from .auth import login
    res = login(ctx.cfg["site"], open_browser=not ctx.args.no_browser)
    ctx.cfg.update(token=res["token"], login=res["login"])
    path = config.save(ctx.cfg)
    print(f"✓ signed in as @{res['login']} — token saved to {path}")
    return 0


def cmd_logout(ctx: Ctx) -> int:
    ctx.cfg.pop("token", None)
    ctx.cfg.pop("login", None)
    config.save(ctx.cfg)
    print("signed out (local token removed)")
    return 0


def cmd_whoami(ctx: Ctx) -> int:
    me = ctx.api.me()
    print(f"@{me['login']} · {ctx.cfg['site']} · "
          f"{'CLI token' if me.get('cli') else 'session'} · "
          f"GitHub sync {'enabled' if me.get('can_sync') else 'unavailable (re-login or set /mogi/sync-pat)'}")
    return 0


def cmd_config(ctx: Ctx) -> int:
    key, value = ctx.args.key, ctx.args.value
    if key and value is not None:
        if key not in ("site", "workspace"):
            raise ApiError(2, "configurable keys: site, workspace")
        ctx.cfg[key] = value
        config.save(ctx.cfg)
    shown = {k: ("<set>" if k == "token" and v else v) for k, v in ctx.cfg.items()}
    print(json.dumps(shown if not key else {key: shown.get(key)}, indent=2, ensure_ascii=False))
    print(f"# {config.config_path()}")
    return 0


def _filter(ctx: Ctx, rows: list[dict]) -> list[dict]:
    a = ctx.args
    q = (getattr(a, "search", "") or "").lower()
    out = []
    for p in rows:
        if getattr(a, "corpus", None) and p["corpus"].lower() != a.corpus.lower():
            continue
        if getattr(a, "genre", None) and (p.get("genre") or "").lower() != a.genre.lower():
            continue
        if getattr(a, "tier", None) and (p.get("tier") or "").upper() != a.tier.upper():
            continue
        if getattr(a, "tag", None) and a.tag not in (p.get("tags") or []):
            continue
        st = getattr(a, "status", None)
        if st == "fresh" and p.get("status"):
            continue
        if st in ("solved", "attempted") and p.get("status") != st:
            continue
        if q and q not in f"{p['id']} {p['title']} {p.get('genre', '')} {' '.join(p.get('tags') or [])}".lower():
            continue
        out.append(p)
    return out


def cmd_ls(ctx: Ctx) -> int:
    rows = sorted(_filter(ctx, ctx.problems()), key=SORTS[ctx.args.sort])
    total = len(rows)
    if ctx.args.limit:
        rows = rows[:ctx.args.limit]
    if ctx.args.json:
        print(json.dumps(rows, indent=2, ensure_ascii=False))
        return 0
    c = ctx.color
    table_rows = []
    for p in rows:
        table_rows.append([
            render.status_glyph(p.get("status", ""), c),
            p["id"], p["title"], p["corpus"], p.get("tier") or "",
            p.get("genre") or "", str(p.get("importance") or 0),
            ("★" * int(p.get("priority") or 0)) or "",
            f"{p.get('pubs') or 1}×·{p.get('family_n') or 0}",
            " ".join(p.get("tags") or []),
        ])
    print(render.table(["", "ID", "Title", "Corpus", "T", "Genre", "Imp", "★", "Freq", "Tags"],
                       table_rows, [1, 5, 46, 6, 1, 22, 3, 5, 7, 20], c))
    solved = sum(1 for p in ctx.problems() if p.get("status") == "solved")
    more = f" (showing {len(rows)} of {total}; -n 0 for all)" if len(rows) < total else ""
    print(render.paint(f"\n{total} problems{more} · {solved}/{len(ctx.problems())} solved overall · "
                       f"sorted by {ctx.args.sort}", "dim", enabled=c))
    return 0


def cmd_open(ctx: Ctx) -> int:
    row = ctx.resolve(ctx.args.id)
    detail = ctx.api.problem(row["pid"])
    d = workspace.materialize(ctx.ws, detail, reset=ctx.args.reset)
    sol = d / workspace.SOLUTION
    print(f"{detail['id']} — {detail['title']}")
    print(f"  {d}")
    print(f"  edit {workspace.SOLUTION}, read {workspace.STATEMENT}; then `mogi run` in that directory")
    if ctx.args.code:
        code = shutil.which("code")
        if not code:
            print("  (VS Code `code` command not found on PATH)")
        else:
            subprocess.run([code, "-g", str(sol)], check=False)
    return 0


def _judge(ctx: Ctx, mode: str) -> int:
    row, d = ctx.current(ctx.args.target)
    if ctx.args.file:
        src = Path(ctx.args.file)
    elif d:
        src = d / workspace.SOLUTION
    else:
        raise ApiError(2, f"no local directory for {row['pid']} — run `mogi open {row['id']}` first "
                          f"or pass --file")
    if not src.exists():
        raise ApiError(2, f"{src} does not exist")
    code = src.read_text(encoding="utf-8")
    if not code.strip():
        raise ApiError(2, f"{src} is empty")
    c = ctx.color
    spin = sys.stdout.isatty()
    if spin:
        print(render.paint(f"judging {row['id']} ({mode})…", "dim", enabled=c), end="", flush=True)
    res = ctx.api.judge(row["pid"], code, mode,
                        on_tick=(lambda _i: print(".", end="", flush=True)) if spin else None)
    if spin:
        print("\r" + " " * 60 + "\r", end="")
    print(render.format_verdict(res, row, c, show_passes=ctx.args.verbose))
    if mode == "submit" and res.get("verdict") == "AC" and row.get("status") != "solved":
        print(render.paint("  🔓 analysis, reference solution and tests are now unlocked on the web page",
                           "dim", enabled=c))
    return 0 if res.get("verdict") == "AC" else 1


def cmd_run(ctx: Ctx) -> int:
    return _judge(ctx, "run")


def cmd_submit(ctx: Ctx) -> int:
    return _judge(ctx, "submit")


def cmd_tag(ctx: Ctx) -> int:
    row = ctx.resolve(ctx.args.id)
    patch: dict = {}
    if ctx.args.reset_genre:
        patch["genre"] = ""
    elif ctx.args.genre is not None:
        patch["genre"] = ctx.args.genre
    if ctx.args.priority is not None:
        patch["priority"] = ctx.args.priority
    tags = None
    if ctx.args.tags is not None:
        tags = [t.strip() for t in ctx.args.tags.split(",") if t.strip()]
    if ctx.args.add_tag or ctx.args.rm_tag:
        tags = list(row.get("tags") or []) if tags is None else tags
        tags += ctx.args.add_tag or []
        tags = [t for t in tags if t not in (ctx.args.rm_tag or [])]
    if tags is not None:
        patch["tags"] = tags
    if not patch:
        raise ApiError(2, "nothing to change — pass --genre/--reset-genre, --priority, --tags/--add-tag/--rm-tag")
    res = ctx.api.set_meta(row["pid"], **patch)
    print(f"{row['id']} — genre {res['genre']}"
          + (f" (corpus: {res['genre_corpus']})" if res.get("genre_corpus") != res["genre"] else "")
          + f" · priority {'★' * int(res.get('priority') or 0) or '—'}"
          + f" · tags {', '.join(res.get('tags') or []) or '—'}")
    return 0


def cmd_pick(ctx: Ctx) -> int:
    rows = [p for p in _filter(ctx, ctx.problems()) if p.get("status") != "solved"]
    if not rows:
        print("nothing unsolved matches — 🎉")
        return 0
    rows.sort(key=SORTS["importance"])
    pick = random.choice(rows[:5]) if ctx.args.random else rows[0]
    c = ctx.color
    print(f"{render.paint(pick['id'], 'bold', enabled=c)} — {pick['title']}  "
          f"[{pick['corpus']} · {pick.get('genre')} · importance {pick.get('importance')}"
          f"{' · ' + '★' * int(pick['priority']) if pick.get('priority') else ''}]")
    if ctx.args.open:
        ctx.args.id = pick["pid"]
        ctx.args.reset = False
        return cmd_open(ctx)
    print(render.paint(f"  mogi open {pick['id']}", "dim", enabled=c))
    return 0


def cmd_stats(ctx: Ctx) -> int:
    rows = ctx.problems()
    c = ctx.color
    by_corpus: dict[str, list[int]] = {}
    by_genre: dict[str, list[int]] = {}
    for p in rows:
        s = p.get("status") == "solved"
        by_corpus.setdefault(p["corpus"], [0, 0])
        by_corpus[p["corpus"]][0] += s
        by_corpus[p["corpus"]][1] += 1
        g = p.get("genre") or "—"
        by_genre.setdefault(g, [0, 0])
        by_genre[g][0] += s
        by_genre[g][1] += 1
    solved = sum(v[0] for v in by_corpus.values())
    print(render.paint(f"{solved}/{len(rows)} solved", "bold", enabled=c) + " · "
          + " · ".join(f"{k} {v[0]}/{v[1]}" for k, v in sorted(by_corpus.items())))
    try:
        ev = ctx.api.activity()["events"]
        week = time.time() * 1000 - 7 * 86400 * 1000
        recent = [e for e in ev if e["ts"] >= week]
        print(f"last 7 days: {len(recent)} judge runs, "
              f"{sum(1 for e in recent if e['verdict'] == 'AC' and e.get('mode') == 'submit')} accepted submissions")
    except ApiError:
        pass
    print()
    table_rows = []
    for g, (s, n) in sorted(by_genre.items(), key=lambda kv: (-(kv[1][1] - kv[1][0]), kv[0].lower())):
        bar = "█" * int(round(10 * s / n)) + "░" * (10 - int(round(10 * s / n)))
        table_rows.append([g, f"{s}/{n}", bar, str(n - s)])
    print(render.table(["Genre", "Solved", "", "Left"], table_rows, [24, 7, 10, 4], c))
    return 0


def cmd_web(ctx: Ctx) -> int:
    url = ctx.cfg["site"].rstrip("/") + "/"
    if ctx.args.id:
        row = ctx.resolve(ctx.args.id)
        from urllib.parse import quote
        url += "problem/" + "/".join(quote(seg, safe="") for seg in row["pid"].split("/"))
    print(url)
    webbrowser.open(url)
    return 0


# ------------------------------------------------------------------ parser
def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="mogi", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--version", action="version", version=f"mogi-cli {__version__}")
    ap.add_argument("--site", help="judge URL (default from config)")
    ap.add_argument("--no-color", action="store_true")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("login", help="sign in via the browser and save a token")
    p.add_argument("--no-browser", action="store_true", help="print the URL instead of opening it")
    p.set_defaults(fn=cmd_login)
    sub.add_parser("logout", help="forget the local token").set_defaults(fn=cmd_logout)
    sub.add_parser("whoami", help="who the token belongs to").set_defaults(fn=cmd_whoami)

    p = sub.add_parser("config", help="show or set site / workspace")
    p.add_argument("key", nargs="?")
    p.add_argument("value", nargs="?")
    p.set_defaults(fn=cmd_config)

    def filters(p):
        p.add_argument("--corpus", help="Amazon | Google")
        p.add_argument("--genre", help="exact genre name (see `mogi stats`)")
        p.add_argument("--tier", help="A (design) | B (algorithm)")
        p.add_argument("--status", choices=["solved", "attempted", "fresh"])
        p.add_argument("--tag", help="only problems carrying this tag")
        p.add_argument("-q", "--search", help="substring of id / title / genre / tags")

    p = sub.add_parser("ls", help="list problems")
    filters(p)
    p.add_argument("--sort", choices=sorted(SORTS), default="importance")
    p.add_argument("-n", "--limit", type=int, default=40, help="rows to show (0 = all)")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_ls)

    p = sub.add_parser("open", help="create the local problem directory")
    p.add_argument("id", help="A16 · Google/C07 · …")
    p.add_argument("--code", action="store_true", help="also open solution.py in VS Code")
    p.add_argument("--reset", action="store_true", help="overwrite solution.py with the stub / your AC code")
    p.set_defaults(fn=cmd_open)

    for name, fn, help_ in (("run", cmd_run, "run the problem's tests (does not count)"),
                            ("submit", cmd_submit, "submit for a verdict that counts")):
        p = sub.add_parser(name, help=help_)
        p.add_argument("target", nargs="?", help="id or path (default: current directory)")
        p.add_argument("--file", help="source file (default: solution.py in the problem directory)")
        p.add_argument("-v", "--verbose", action="store_true", help="also list passing checks")
        p.set_defaults(fn=fn)

    p = sub.add_parser("tag", help="categorise: genre override, priority stars, tags")
    p.add_argument("id")
    p.add_argument("--genre")
    p.add_argument("--reset-genre", action="store_true", help="back to the corpus genre")
    p.add_argument("--priority", type=int, choices=range(0, 6), metavar="0-5")
    p.add_argument("--tags", help="replace tags: comma separated")
    p.add_argument("--add-tag", action="append")
    p.add_argument("--rm-tag", action="append")
    p.set_defaults(fn=cmd_tag)

    p = sub.add_parser("pick", help="the most important unsolved problem")
    filters(p)
    p.add_argument("--random", action="store_true", help="random among the top 5 instead of the top 1")
    p.add_argument("--open", action="store_true", help="also create its directory")
    p.set_defaults(fn=cmd_pick)

    sub.add_parser("stats", help="progress by corpus and genre").set_defaults(fn=cmd_stats)
    p = sub.add_parser("web", help="open the dashboard (or a problem) in the browser")
    p.add_argument("id", nargs="?")
    p.set_defaults(fn=cmd_web)
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.fn(Ctx(args))
    except ApiError as e:
        print(f"mogi: {e.msg}", file=sys.stderr)
        return 2
    except TimeoutError as e:
        print(f"mogi: {e}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print()
        return 130


if __name__ == "__main__":
    sys.exit(main())
