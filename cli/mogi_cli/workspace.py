"""The local workspace: one directory per problem.

    <workspace>/<Corpus>/<slug>/
        problem.md    statement · required API · links (regenerated on every `open`)
        solution.py   your code (created from the stub, or from your accepted solution)
        .mogi.json    marker: which problem this directory is

`mogi run` / `mogi submit` find the problem by walking up from the current directory
(or the given file) to the nearest `.mogi.json`.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

MARKER = ".mogi.json"
SOLUTION = "solution.py"
STATEMENT = "problem.md"


def problem_dir(ws: Path, p: dict) -> Path:
    slug = p.get("slug") or re.sub(r"[^A-Za-z0-9_]+", "_", f"{p['id']}_{p.get('title', '')}")[:60]
    return ws / p["corpus"] / slug


def read_marker(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) and data.get("pid") else None
    except (OSError, ValueError):
        return None


def find_marker(start: Path) -> tuple[Path, dict] | None:
    """Walk up from a file or directory to the nearest .mogi.json."""
    cur = start.resolve()
    if cur.is_file():
        cur = cur.parent
    for d in (cur, *cur.parents):
        m = read_marker(d / MARKER)
        if m:
            return d, m
    return None


def marker_dirs(ws: Path) -> list[tuple[Path, dict]]:
    out = []
    for path in sorted(ws.glob(f"*/*/{MARKER}")):
        m = read_marker(path)
        if m:
            out.append((path.parent, m))
    return out


def dir_for_pid(ws: Path, pid: str) -> Path | None:
    for d, m in marker_dirs(ws):
        if m.get("pid") == pid:
            return d
    return None


def render_problem_md(p: dict) -> str:
    pr = p.get("practice") or {}
    rows = [
        ("Corpus", f"{p.get('corpus', '')} · Tier {p.get('tier', '')}"
                   + (f" · {p['round']}" if p.get("round") else "")
                   + (f" · published {p['published']}" if p.get("published") else "")),
        ("Genre", p.get("genre", "") + (f" (corpus: {p['genre_corpus']})"
                                        if p.get("genre_corpus") and p.get("genre_corpus") != p.get("genre") else "")),
        ("Importance", f"{p.get('importance', 0)}/100"
                       + (f" · shape rank #{p['rank']}" if p.get("rank") else "")
                       + (f" · priority {'★' * int(p['priority'])}" if p.get("priority") else "")),
        ("Seen", f"{p.get('pubs', 1)} publication(s) · {p.get('family_n', 0)} problems share the genre"),
        ("Source", p.get("link") or "—"),
    ]
    if pr.get("url"):
        rows.append(("Practice", f"[{pr.get('label', 'judge')}]({pr['url']}) {'⭐' * int(pr.get('stars') or 0)}"
                                 + (f" — {pr['note']}" if pr.get("note") else "")))
    if p.get("tags"):
        rows.append(("Tags", ", ".join(p["tags"])))
    table = "| | |\n|---|---|\n" + "\n".join(f"| **{k}** | {v} |" for k, v in rows)
    required = " ".join(f"`{r}`" for r in p.get("required") or []) or "—"
    out = [
        f"# {p.get('id', '')} — {p.get('title', '')}",
        "",
        table,
        "",
        p.get("statement", "").strip(),
        "",
        "## Required API",
        "",
        f"The tests call these top-level names: {required}",
        "",
        "Your own `if __name__ == \"__main__\":` block is stripped before judging, so scratch tests there are safe.",
        "",
        "```python",
        (p.get("stub") or "").rstrip(),
        "```",
        "",
        "---",
        f"`mogi run` · `mogi submit` from this directory, or `mogi run {p.get('pid', '')}` from anywhere.",
        "",
    ]
    return "\n".join(out)


def materialize(ws: Path, p: dict, *, reset: bool = False) -> Path:
    """Create/refresh the problem directory. solution.py is never overwritten
    unless `reset` is given; problem.md and the marker always are."""
    d = problem_dir(ws, p)
    d.mkdir(parents=True, exist_ok=True)
    (d / STATEMENT).write_text(render_problem_md(p), encoding="utf-8")
    sol = d / SOLUTION
    if reset or not sol.exists():
        seed = p.get("ac_code") or p.get("stub") or ""
        header = (f"# {p.get('pid', '')} — {p.get('title', '')}\n"
                  f"# statement: ./{STATEMENT}  ·  judge: mogi run / mogi submit\n\n")
        sol.write_text(header + seed.rstrip() + "\n", encoding="utf-8")
    (d / MARKER).write_text(json.dumps({
        "pid": p["pid"], "id": p.get("id"), "title": p.get("title"),
        "corpus": p.get("corpus"), "slug": p.get("slug"),
    }, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return d
