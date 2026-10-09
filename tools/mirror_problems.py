#!/usr/bin/env python3
"""Mirror every question into the solutions repo, next to the accepted solutions.

The judge pushes an accepted solution to `<Corpus>/<slug>.py`; this tool writes the
matching question to `<Corpus>/<slug>.md` (statement, required API, starter stub,
source/practice links — no analysis or reference solution, so the repo stays
spoiler-free) and regenerates README.md as a browsable index sorted by importance,
marking problems that already have an accepted solution.

    python3 tools/mirror_problems.py /path/to/真題 --repo shiroyang/oj-solutions
    python3 tools/mirror_problems.py /path/to/真題 --repo shiroyang/oj-solutions --dry-run

Pushes with the `gh` CLI's token through a one-off credential helper, so no git
config is changed. Re-running is idempotent: unchanged files produce no commit.
"""
from __future__ import annotations

import argparse
import datetime as dt
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ingest import collect, CORPORA  # noqa: E402

JUDGE = "https://d24vqc5jsqa7l8.cloudfront.net"


def with_meta_rows(statement: str, title: str, rows: list[tuple[str, str]]) -> str:
    """The visible statement already opens with the corpus's `# ID — title` and its
    front-matter table; append our rows to that table instead of adding a second
    header. Falls back to synthesising a header if a statement has no table."""
    lines = statement.strip().splitlines()
    first_section = next((i for i, ln in enumerate(lines) if ln.startswith("## ")), len(lines))
    table_rows = [i for i in range(first_section) if lines[i].startswith("| **")]
    extra = [f"| **{k}** | {v} |" for k, v in rows]
    if not table_rows:
        return "\n".join([f"# {title}", "", "| | |", "|---|---|", *extra, "", *lines])
    cut = table_rows[-1] + 1
    return "\n".join(lines[:cut] + extra + lines[cut:])


def problem_md(it: dict) -> str:
    rows = [
        ("Genre", it["genre"] + f" ({it['family_n']} problems share it)"),
        ("Importance", f"{it['importance']}/100" + (f" · shape rank #{it['rank']}" if it["rank"] else "")
                       + f" · seen in {it['pubs']} publication(s)"),
        ("Judge", f"[{it['corpus']}/{it['id']} on mogi]({JUDGE}/problem/{it['corpus']}/{it['id']})"),
        ("Solution", f"[`{it['slug']}.py`](./{it['slug']}.py) once accepted"),
    ]
    required = " ".join(f"`{r}`" for r in it["required"]) or "—"
    return "\n".join([
        with_meta_rows(it["statement"], f"{it['id']} — {it['title']}", rows),
        "",
        "## Required API",
        "",
        f"The tests call these top-level names: {required}",
        "",
        "```python",
        it["stub"].rstrip(),
        "```",
        "",
        "---",
        "Mirrored from the 真題 corpus by `tools/mirror_problems.py` (statement only — analysis and "
        "reference solution stay in the corpus until you solve it on the judge).",
        "",
    ])


def readme_md(items: list[dict], accepted: set[str]) -> str:
    out = [
        "# oj-solutions",
        "",
        "My interview-prep corpus — **every question**, plus my **accepted solutions** as they land.",
        "",
        f"Questions (`<Corpus>/<slug>.md`) are mirrored from the 真題 corpus by "
        f"[mogi](https://github.com/shiroyang/mogi)'s `tools/mirror_problems.py`; solutions "
        f"(`<Corpus>/<slug>.py`) are committed by the judge the moment a submission passes all of a "
        f"problem's checks. Each solution carries its verdict line: checks passed, runtime, source link.",
        "",
        f"**{len(accepted)} / {len(items)} accepted** — index regenerated {dt.date.today().isoformat()}; "
        f"the ✅ marks are as of that run, the `.py` files are always current.",
        "",
    ]
    for corpus in CORPORA:
        rows = sorted((i for i in items if i["corpus"] == corpus),
                      key=lambda i: (-i["importance"], i["pid"]))
        done = sum(1 for i in rows if i["slug"] in accepted)
        out += [f"## {corpus} — {done} / {len(rows)} accepted", "",
                "| | ID | Problem | Genre | Importance | Seen |",
                "|---|---|---|---|---|---|"]
        for i in rows:
            mark = "✅" if i["slug"] in accepted else "·"
            sol = f" · [solution](./{corpus}/{i['slug']}.py)" if i["slug"] in accepted else ""
            title = i["title"].replace("|", "\\|")
            out.append(f"| {mark} | `{i['id']}` | [{title}](./{corpus}/{i['slug']}.md){sol} | {i['genre']} | "
                       f"{i['importance']}{' · #' + str(i['rank']) if i['rank'] else ''} | "
                       f"{i['pubs']}× · {i['family_n']} |")
        out.append("")
    out += ["Importance 0–100 = shape rank (Amazon README \"Start here\") + genre size + extra publications "
            "+ confidence stars + 6 if Tier A; see the mogi README. Seen = publications × · problems sharing the genre.", ""]
    return "\n".join(out)


def git(*args: str, cwd: Path, token: str | None = None) -> str:
    cmd = ["git"]
    if token:
        cmd += ["-c", "credential.helper=!f() { echo username=x-access-token; echo password=" + token + "; }; f"]
    cmd += list(args)
    return subprocess.run(cmd, cwd=cwd, check=True, capture_output=True, text=True).stdout


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("corpus_root", type=Path)
    ap.add_argument("--repo", default="shiroyang/oj-solutions")
    ap.add_argument("--dry-run", action="store_true", help="write into a temp clone, don't push")
    ap.add_argument("--workdir", type=Path, help="reuse this clone instead of a fresh temp dir")
    args = ap.parse_args()

    items, skipped, _ = collect(args.corpus_root.expanduser())
    for s in skipped:
        print(f"  skipped {s}")
    token = subprocess.run(["gh", "auth", "token"], check=True, capture_output=True, text=True).stdout.strip()
    work = args.workdir or Path(tempfile.mkdtemp(prefix="oj-solutions-"))
    if not (work / ".git").exists():
        git("clone", "--quiet", f"https://github.com/{args.repo}.git", str(work), cwd=Path("/tmp"), token=token)
    else:
        git("pull", "--quiet", "--ff-only", cwd=work, token=token)

    accepted = {p.stem for c in CORPORA for p in (work / c).glob("*.py")} if work.exists() else set()
    written = 0
    for it in items:
        path = work / it["corpus"] / f"{it['slug']}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        text = problem_md(it)
        if not path.exists() or path.read_text(encoding="utf-8") != text:
            path.write_text(text, encoding="utf-8")
            written += 1
    (work / "README.md").write_text(readme_md(items, accepted), encoding="utf-8")

    status = git("status", "--porcelain", cwd=work)
    changed = [ln for ln in status.splitlines() if ln.strip()]
    print(f"{len(items)} questions · {len(accepted)} accepted · {written} question files (re)written · "
          f"{len(changed)} paths changed in {work}")
    if not changed:
        print("nothing to commit")
        return 0
    if args.dry_run:
        print("dry run — not committing. Sample:\n" + "\n".join(changed[:8]))
        return 0
    git("add", "-A", cwd=work)
    git("-c", "user.name=mogi", "-c", "user.email=mogi@users.noreply.github.com", "commit", "--quiet", "-m",
        f"mirror questions: {len(items)} problems, {len(accepted)} accepted", cwd=work)
    git("push", "--quiet", "origin", "HEAD", cwd=work, token=token)
    print(f"pushed to https://github.com/{args.repo}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
