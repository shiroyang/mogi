#!/usr/bin/env python3
"""Mirror every question and a reference solution into the solutions repo.

Per problem, next to the judge's accepted-solution file `<Corpus>/<slug>.py`:

    <Corpus>/<slug>.md             the question — statement, examples, required API,
                                   starter stub; spoiler-free
    <Corpus>/<slug>.reference.md   how it is solved, the core code explained, edge
                                   cases, complexity, follow-ups — the corpus's own
                                   analysis regrouped — then the complete clean
                                   implementation and the tests the judge runs

and README.md is regenerated as an index sorted by importance, marking problems that
already have an accepted solution.

    python3 tools/mirror_problems.py /path/to/真題 --repo shiroyang/mogi-solutions
    python3 tools/mirror_problems.py /path/to/真題 --dry-run

Pushes with the `gh` CLI's token through a one-off credential helper, so no git
config is changed. Re-running is idempotent: unchanged files produce no commit.
"""
from __future__ import annotations

import argparse
import datetime as dt
import re
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ingest import collect, CORPORA  # noqa: E402

JUDGE = "https://mogi-judge.vercel.app"

# The corpus's analysis sections, regrouped for a reader who wants the answer.
# Keys are matched as substrings of the lower-cased section title, first group wins.
GROUPS: list[tuple[str, tuple[str, ...]]] = [
    ("How it's solved", ("clarifying", "brute force", "approach", "growth axis", "structure choice", "four boxes")),
    ("The core code, explained", ("code",)),
    ("Check it by hand", ("hand-trace",)),
    ("Edge cases", ("edge cases",)),
    ("Complexity", ("complexity",)),
    ("What changes in production", ("production",)),
    ("Follow-ups the interviewer asks", ("follow-up ladder", "escalation ladder")),
    ("Note on the source's solution", ("note on the source",)),
]


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
        ("Reference", f"[`{it['slug']}.reference.md`](./{it['slug']}.reference.md) — how it is solved, with the code"),
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
        "Mirrored from the 真題 corpus by `tools/mirror_problems.py` (statement only — the walkthrough is in the "
        "reference file, and the judge unlocks it after your first accepted submission).",
        "",
    ])


def sections(analysis: str) -> list[tuple[str, str]]:
    parts = re.split(r"(?m)^(## .+)$", analysis)
    out = []
    for i in range(1, len(parts), 2):
        title = re.sub(r"^##\s*(\d+\.\s*)?", "", parts[i]).strip()   # "## 7. Code" / "## Note on …"
        title = re.sub(r"\s*\*\(ritual line \d+\)\*\s*$", "", title).strip()
        body = parts[i + 1].strip() if i + 1 < len(parts) else ""
        if body:
            out.append((title, body))
    return out


def reference_md(it: dict) -> str:
    grouped: dict[str, list[tuple[str, str]]] = {g: [] for g, _ in GROUPS}
    other: list[tuple[str, str]] = []
    for title, body in sections(it["analysis"]):
        key = title.lower()
        for g, keys in GROUPS:
            if any(k in key for k in keys):
                grouped[g].append((title, body))
                break
        else:
            other.append((title, body))
    m = re.search(r"(\d+)\s+self-checks", it.get("solution_row", ""))
    checks = f"all {m.group(1)} checks" if m else "every check"
    lines = [
        f"# {it['id']} — {it['title']} · reference solution",
        "",
        f"> How it is solved, the core code explained, then the complete implementation that passes "
        f"{checks} on the judge. The question is in [`{it['slug']}.md`](./{it['slug']}.md); "
        f"your own accepted solution lands in `{it['slug']}.py`. "
        f"[Open on mogi]({JUDGE}/problem/{it['corpus']}/{it['id']}).",
        "",
        f"**{it['corpus']} · Tier {it['tier']} · {it['genre']} · importance {it['importance']}/100**",
        "",
    ]
    for g, _ in GROUPS:
        if not grouped[g]:
            continue
        lines += [f"## {g}", ""]
        for title, body in grouped[g]:
            if len(grouped[g]) > 1:  # several corpus sections share the group: keep their titles
                lines += [f"### {title}", ""]
            lines += [body, ""]
    for title, body in other:
        lines += [f"## {title}", "", body, ""]
    lines += [
        "## The complete implementation",
        "",
        "Standard library only. This is the module the corpus ships; the judge appends the problem's own "
        "tests to it (shown below) and requires the contract line `N/N checks passed`.",
        "",
        "```python",
        it["reference"].rstrip(),
        "```",
        "",
        "<details><summary>The tests the judge runs</summary>",
        "",
        "```python",
        it["harness"].rstrip(),
        "```",
        "",
        "</details>",
        "",
    ]
    return "\n".join(lines)


def readme_md(items: list[dict], accepted: set[str], repo: str) -> str:
    name = repo.split("/", 1)[-1]
    out = [
        f"# {name}",
        "",
        "My interview-prep corpus: **every question**, a **reference solution with an explanation** for each, "
        "and **my own accepted solutions** as they land.",
        "",
        "Per problem, in `<Corpus>/`:",
        "",
        "- `<slug>.md` — the question: statement, examples, required API, starter stub (spoiler-free)",
        "- `<slug>.reference.md` — how it is solved, the core code explained, edge cases, complexity, "
        "the follow-ups an interviewer asks, then the complete implementation and the tests",
        "- `<slug>.py` — my accepted solution, committed by [mogi](https://github.com/shiroyang/mogi) the moment "
        "a submission passes all of a problem's checks (header: checks, runtime, source link)",
        "",
        f"Questions and references are regenerated from the 真題 corpus by mogi's `tools/mirror_problems.py`. "
        f"**{len(accepted)} / {len(items)} accepted** — index regenerated {dt.date.today().isoformat()}; "
        f"the ✅ marks are as of that run, the `.py` files are always current.",
        "",
    ]
    for corpus in CORPORA:
        rows = sorted((i for i in items if i["corpus"] == corpus),
                      key=lambda i: (-i["importance"], i["pid"]))
        done = sum(1 for i in rows if i["slug"] in accepted)
        out += [f"## {corpus} — {done} / {len(rows)} accepted", "",
                "| | ID | Problem | Genre | Importance | Seen | |",
                "|---|---|---|---|---|---|---|"]
        for i in rows:
            mark = "✅" if i["slug"] in accepted else "·"
            title = i["title"].replace("|", "\\|")
            links = f"[reference](./{corpus}/{i['slug']}.reference.md)"
            if i["slug"] in accepted:
                links += f" · [mine](./{corpus}/{i['slug']}.py)"
            out.append(f"| {mark} | `{i['id']}` | [{title}](./{corpus}/{i['slug']}.md) | {i['genre']} | "
                       f"{i['importance']}{' · #' + str(i['rank']) if i['rank'] else ''} | "
                       f"{i['pubs']}× · {i['family_n']} | {links} |")
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
    ap.add_argument("--repo", default="shiroyang/mogi-solutions")
    ap.add_argument("--dry-run", action="store_true", help="write into the clone, don't commit or push")
    ap.add_argument("--workdir", type=Path, help="reuse this clone instead of a fresh temp dir")
    args = ap.parse_args()

    items, skipped, _ = collect(args.corpus_root.expanduser())
    for s in skipped:
        print(f"  skipped {s}")
    token = subprocess.run(["gh", "auth", "token"], check=True, capture_output=True, text=True).stdout.strip()
    work = args.workdir or Path(tempfile.mkdtemp(prefix="mogi-solutions-"))
    url = f"https://github.com/{args.repo}.git"
    if not (work / ".git").exists():
        git("clone", "--quiet", url, str(work), cwd=Path("/tmp"), token=token)
    else:
        git("remote", "set-url", "origin", url, cwd=work)
        git("pull", "--quiet", "--ff-only", cwd=work, token=token)

    accepted = {p.stem for c in CORPORA for p in (work / c).glob("*.py")}
    written = 0
    for it in items:
        d = work / it["corpus"]
        d.mkdir(parents=True, exist_ok=True)
        for path, text in ((d / f"{it['slug']}.md", problem_md(it)),
                           (d / f"{it['slug']}.reference.md", reference_md(it))):
            if not path.exists() or path.read_text(encoding="utf-8") != text:
                path.write_text(text, encoding="utf-8")
                written += 1
    (work / "README.md").write_text(readme_md(items, accepted, args.repo), encoding="utf-8")

    changed = [ln for ln in git("status", "--porcelain", cwd=work).splitlines() if ln.strip()]
    print(f"{len(items)} questions · {len(accepted)} accepted · {written} files (re)written · "
          f"{len(changed)} paths changed in {work}")
    if not changed:
        print("nothing to commit")
        return 0
    if args.dry_run:
        print("dry run — not committing. Sample:\n" + "\n".join(changed[:8]))
        return 0
    git("add", "-A", cwd=work)
    git("-c", "user.name=mogi", "-c", "user.email=mogi@users.noreply.github.com", "commit", "--quiet", "-m",
        f"mirror questions + reference solutions: {len(items)} problems, {len(accepted)} accepted", cwd=work)
    git("push", "--quiet", "origin", "HEAD", cwd=work, token=token)
    print(f"pushed to https://github.com/{args.repo}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
