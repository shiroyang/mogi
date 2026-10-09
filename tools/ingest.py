#!/usr/bin/env python3
"""Ingest the 真題 corpus into the mogi DynamoDB table.

For each problem: pair the statement .md with its solution .py, split the solution
into reference + harness (splitter.py), split the statement into the always-visible
part and the spoiler analysis, derive the ranking metadata — genre, how often the
problem/shape was seen, an importance score — from the front matter and the corpus
README, and write one META item plus one slim PROBLIST item.

Problem ids are corpus-qualified (`Amazon/A16`, `Google/C07`): the two corpora reuse
bare ids, and an earlier ingest silently let Google's `C07` overwrite Amazon's.

    python3 tools/ingest.py /path/to/真題 --table mogi --region eu-west-1
    python3 tools/ingest.py /path/to/真題 --dry-run                 # parse + report only
    python3 tools/ingest.py /path/to/真題 --dry-run --show Amazon/A16
    python3 tools/ingest.py /path/to/真題 --prune-stale             # also drop rows no longer in the corpus

Importance (0–100, documented in the README and shown as a tooltip in the UI):

    rank_pts    45,40,…,15 for shape ranks 1–7 in the Amazon README's "Start here" table
    family_pts  2 × min(problems sharing the genre in this corpus, 12)
    pubs_pts    8 × min(publications − 1, 2)   # Alt source URL, † republished twin
    conf_pts    4 × confidence stars (1–3)      # how verbatim the published statement is
    tier_pts    6 if Tier A (design & implement)
"""
from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend" / "judge"))
from splitter import split_solution  # noqa: E402

CORPORA = ("Amazon", "Google")

# Sections shown before solving. Everything else is analysis (unlocked after AC).
SAFE_SECTIONS = {
    "statement (as published)",
    "two examples — one normal, one edge",
    "worked example — input → expected output",
}
SPOILER_META_ROWS = ("solution", "structure", "growth axis")
RANK_PTS = {1: 45, 2: 40, 3: 35, 4: 30, 5: 25, 6: 20, 7: 15}
ID_RE = r"`([A-Z]\d+[a-z]?)`"


# ---------------------------------------------------------------- statement
def split_statement(md: str) -> tuple[str, str, dict]:
    """Return (visible, analysis, meta). The front-matter table rows feed meta;
    spoiler rows are dropped from the visible copy."""
    meta: dict[str, str] = {}
    title = ""
    m = re.match(r"^# (.+)$", md, re.M)
    if m:
        title = re.sub(r"^[A-Z]\d+[a-z]?\s*[—-]\s*", "", m.group(1)).strip()
    for row in re.finditer(r"^\|\s*\*\*(.+?)\*\*\s*\|\s*(.+?)\s*\|$", md, re.M):
        meta[row.group(1).strip().lower()] = row.group(2).strip()

    chunks = re.split(r"(?m)^(## .+)$", md)
    head = chunks[0]
    head = "\n".join(
        ln for ln in head.splitlines()
        if not any(ln.lower().startswith(f"| **{k}") for k in SPOILER_META_ROWS)
    )
    visible, analysis = [head], []
    for i in range(1, len(chunks), 2):
        header, body = chunks[i], chunks[i + 1] if i + 1 < len(chunks) else ""
        norm = re.sub(r"^\d+\.\s*", "", header[3:]).strip().lower()
        norm = re.sub(r"\s*\*\(.*\)\*\s*$", "", norm)  # "(ritual line N)" suffixes
        (visible if norm in SAFE_SECTIONS else analysis).append(header + body)
    return "\n".join(visible).strip(), "\n".join(analysis).strip(), {"title": title, **meta}


# ---------------------------------------------------------------- metadata
def readme_index(corpus_dir: Path) -> tuple[dict[str, str], dict[str, int], set[str]]:
    """(id → canonical family, id → shape rank, ids marked † as republished twins)
    from the corpus README: the "Index by family" table that every corpus carries,
    and — Amazon only — the ranked-shapes table under "Start here"."""
    path = corpus_dir / "README.md"
    md = path.read_text(encoding="utf-8") if path.exists() else ""
    family: dict[str, str] = {}
    rank: dict[str, int] = {}
    twins: set[str] = set()

    sec = md.split("## Index by family", 1)
    if len(sec) == 2:
        body = sec[1].split("\n## ", 1)[0]
        for m in re.finditer(r"^\|\s*\*\*(.+?)\*\*\s*\|\s*\d+\s*\|\s*\d+\s*\|(.+)\|\s*$",
                             body, re.M):
            fam = m.group(1).strip()
            for idm in re.finditer(ID_RE + r"(\s*†)?", m.group(2)):
                family[idm.group(1)] = fam
                if idm.group(2):
                    twins.add(idm.group(1))

    sec = md.split("## Start here", 1)
    if len(sec) == 2:
        body = sec[1].split("\n## ", 1)[0]
        for m in re.finditer(r"^\|\s*\*\*(\d+)\*\*\s*\|[^|]*\|([^|]*)\|", body, re.M):
            for idm in re.finditer(ID_RE, m.group(2)):
                rank.setdefault(idm.group(1), int(m.group(1)))  # best rank wins
    return family, rank, twins


def norm_family(raw: str) -> str:
    """Fallback when the README does not list the id: the leading family token of
    the front-matter row, e.g. 'graph (connected components)' → 'graph'."""
    s = raw.strip().strip("`").strip()
    s = re.split(r"\s+—\s+|\s+\*\*\+\*\*\s+|\s+\+\s+|\s+·\s+|\s+→\s+|\s*\(", s)[0]
    return s.strip("` ").strip() or "misc"


def stars(text: str) -> int:
    return text.count("⭐")


def parse_practice(row: str) -> dict:
    """'⭐⭐ same core — [LC 1603 Design Parking System](url) *Easy* — …' →
    {stars, url, label, note}. A row starting with '—' means no judge hosts it."""
    row = row.strip()
    if not row or row.startswith("—"):
        return {"stars": 0, "url": "", "label": "", "note": row.lstrip("— ").strip()[:200]}
    head = re.split(r"\s+—\s+", row, maxsplit=1)
    link = re.search(r"\[([^\]]+)\]\((https?://[^)\s]+)\)", row)
    note = re.split(r"\s+—\s+", row)[-1] if row.count(" — ") >= 2 else ""
    return {"stars": min(stars(head[0]), 3), "url": link.group(2) if link else "",
            "label": link.group(1) if link else "", "note": note.strip()[:200]}


def parse_round(row: str) -> str:
    tok = re.split(r"[\s(—]", row.strip(), maxsplit=1)[0].strip(" -—").upper()
    if tok.startswith("VO") or tok in ("ONSITE", "ONSITE."):
        return "VO" if tok.startswith("VO") else "onsite"
    if tok.startswith("OA"):
        return tok if tok == "OA/VO" else "OA"
    if tok.startswith("PHONE"):
        return "phone"
    if tok.startswith("INTERVIEW"):
        return "interview"
    return "unknown"


def importance(it: dict) -> int:
    score = RANK_PTS.get(it.get("rank") or 0, 0)
    score += 2 * min(it["family_n"], 12)
    score += 8 * min(it["pubs"] - 1, 2)
    score += 4 * it["confidence"]
    score += 6 if it["tier"] == "A" else 0
    return min(score, 100)


# ---------------------------------------------------------------- collect
def collect(corpus_root: Path) -> tuple[list[dict], list[str], dict]:
    items, skipped = [], []
    stats = {"readme_genre": 0, "fallback_genre": 0, "ranked": 0, "twins": 0}
    for corpus in CORPORA:
        cdir = corpus_root / corpus
        fam_idx, rank_idx, twins = readme_index(cdir)
        # IDs: Amazon pairs A03-slug.md <-> A03_slug.py; Google shares the full
        # stem (C01a_B_slug). The bare id is the stem up to the first - or _.
        sols = {re.split(r"[-_]", p.stem)[0]: p for p in (cdir / "solutions").glob("*.py")}
        batch = []
        for md_path in sorted((cdir / "problems").glob("*.md")):
            bare = re.split(r"[-_]", md_path.stem)[0]
            sol = sols.get(bare)
            if not sol:
                skipped.append(f"{corpus}/{bare}: statement without a solution file")
                continue
            visible, analysis, meta = split_statement(md_path.read_text(encoding="utf-8"))
            try:
                s = split_solution(sol.read_text(encoding="utf-8"))
            except Exception as e:
                skipped.append(f"{corpus}/{bare}: split failed — {e}")
                continue
            # "A (design) — …" but also "**A (design)** — upgraded …" on the four
            # Amazon files that carry a B id and were upgraded to Tier A.
            tier = (re.sub(r"^[\s*`_]+", "", meta.get("tier", "")) + " ")[0].upper().strip()
            link_m = re.search(r"https?://\S+", meta.get("source", ""))
            alt_m = re.search(r"https?://\S+", meta.get("alt source", ""))
            if bare in fam_idx:
                genre = fam_idx[bare]
                stats["readme_genre"] += 1
            else:
                genre = norm_family(meta.get("family", ""))
                stats["fallback_genre"] += 1
            rank = rank_idx.get(bare)
            stats["ranked"] += bool(rank)
            stats["twins"] += bare in twins
            pub_m = re.search(r"\d{4}-\d{2}-\d{2}", meta.get("published", ""))
            batch.append({
                "pid": f"{corpus}/{bare}", "id": bare, "corpus": corpus, "slug": sol.stem,
                "title": meta.get("title") or bare,
                "tier": tier, "family": meta.get("family", ""), "genre": genre,
                "round": parse_round(meta.get("round tag", "")),
                "published": pub_m.group(0) if pub_m else "",
                "confidence": max(1, min(stars(meta.get("confidence", "")) or 2, 3)),
                "pubs": 1 + bool(alt_m) + (bare in twins),
                "rank": rank,
                "practice": parse_practice(meta.get("practice", "")),
                "link": link_m.group(0).rstrip("|) ") if link_m else "",
                "alt_link": alt_m.group(0).rstrip("|) ") if alt_m else "",
                "statement": visible, "analysis": analysis,
                "reference": s.reference, "harness": s.harness,
                "imports": s.imports, "required": s.required, "stub": s.stub,
            })
        sizes = Counter(it["genre"] for it in batch)
        for it in batch:
            it["family_n"] = sizes[it["genre"]]
            it["importance"] = importance(it)
        items.extend(batch)
    return items, skipped, stats


DEFAULT_TIME_LIMIT_S = 20
VERIFY_TIME_LIMIT_S = 100   # local verification budget
MAX_TIME_LIMIT_S = 110      # must stay under the judge Lambda's 120 s timeout


def time_limit_for(reference_ms: int) -> int:
    """Per-problem wall-clock limit. Most harnesses finish in well under a second
    and get the 20 s default. A harness with a heavy self-check (B17 runs a
    brute-force oracle over 3000 random inputs, ~21 s on a laptop) gets 4× its
    local reference time plus slack — the 1-vCPU Lambda measured ~2.7× slower
    than an Apple-silicon laptop on pure-Python loops — capped below the judge
    Lambda's own timeout so a TLE is still reported rather than a crash."""
    if reference_ms < 5_000:
        return DEFAULT_TIME_LIMIT_S
    return max(DEFAULT_TIME_LIMIT_S, min(MAX_TIME_LIMIT_S, int(reference_ms * 4 / 1000) + 10))


def verify(items: list[dict]) -> int:
    """Run each reference through the runner to stamp the check count and the
    per-problem time limit."""
    from runner import judge
    bad, slow = 0, []
    for i, it in enumerate(items, 1):
        r = judge(it["reference"], it["harness"], it["imports"], time_limit_s=VERIFY_TIME_LIMIT_S)
        if r["verdict"] == "AC":
            it["checks"] = r["total"]
            it["time_limit_s"] = time_limit_for(r["ms"])
            if it["time_limit_s"] != DEFAULT_TIME_LIMIT_S:
                slow.append(f"{it['pid']} ({r['ms']} ms → limit {it['time_limit_s']} s)")
        else:
            bad += 1
            print(f"  VERIFY-FAIL {it['pid']}: {r['verdict']} {r['detail'][:100]}")
        if i % 50 == 0:
            print(f"  verified {i}/{len(items)}")
    if slow:
        print(f"  slow references given a longer limit: {', '.join(slow)}")
    return bad


def problist_row(it: dict) -> dict:
    return {
        "pk": "PROBLIST", "sk": it["pid"], "id": it["id"], "title": it["title"],
        "corpus": it["corpus"], "tier": it["tier"], "genre": it["genre"],
        "family": it["family"], "family_n": it["family_n"], "rank": it["rank"],
        "pubs": it["pubs"], "confidence": it["confidence"], "importance": it["importance"],
        "practice_stars": it["practice"]["stars"], "practice_url": it["practice"]["url"],
        "published": it["published"], "round": it["round"], "checks": it.get("checks", 0),
        "time_limit_s": it.get("time_limit_s", DEFAULT_TIME_LIMIT_S),
    }


def upload(items: list[dict], table_name: str, region: str, prune: bool):
    import boto3
    table = boto3.resource("dynamodb", region_name=region).Table(table_name)
    with table.batch_writer() as batch:
        for it in items:
            batch.put_item(Item={"pk": f"PROB#{it['pid']}", "sk": "META", **it})
            batch.put_item(Item=problist_row(it))
    print(f"uploaded {len(items)} problems to {table_name} ({region})")
    if prune:
        keep = {it["pid"] for it in items}
        stale, start = [], None
        while True:
            kw = {"KeyConditionExpression": "pk = :p",
                  "ExpressionAttributeValues": {":p": "PROBLIST"},
                  "ProjectionExpression": "sk"}
            if start:
                kw["ExclusiveStartKey"] = start
            page = table.query(**kw)
            stale += [i["sk"] for i in page["Items"] if i["sk"] not in keep]
            start = page.get("LastEvaluatedKey")
            if not start:
                break
        with table.batch_writer() as batch:
            for sk in stale:
                batch.delete_item(Key={"pk": "PROBLIST", "sk": sk})
                batch.delete_item(Key={"pk": f"PROB#{sk}", "sk": "META"})
        print(f"pruned {len(stale)} stale problem rows: {stale[:12]}{'…' if len(stale) > 12 else ''}")


def report(items: list[dict], skipped: list[str], stats: dict):
    print(f"parsed {len(items)} problems "
          f"({sum(1 for i in items if i['corpus'] == 'Amazon')} Amazon / "
          f"{sum(1 for i in items if i['corpus'] == 'Google')} Google)")
    for s in skipped:
        print(f"  skipped {s}")
    thin = [i["pid"] for i in items if len(i["statement"]) < 200]
    if thin:
        print(f"  ⚠ thin statements (<200 chars): {thin}")
    print(f"  genre from README: {stats['readme_genre']} · fallback from front matter: "
          f"{stats['fallback_genre']} · ranked shapes: {stats['ranked']} · † twins: {stats['twins']}")
    bare = Counter(i["id"] for i in items)
    dupes = sorted(k for k, v in bare.items() if v > 1)
    print(f"  bare ids shared by both corpora (now distinct pids): {dupes}")
    for corpus in CORPORA:
        rows = [i for i in items if i["corpus"] == corpus]
        genres = Counter(i["genre"] for i in rows)
        print(f"  {corpus}: {len(genres)} genres — " + ", ".join(
            f"{g} {n}" for g, n in genres.most_common()))
    print("  top 12 by importance:")
    for it in sorted(items, key=lambda i: -i["importance"])[:12]:
        print(f"    {it['importance']:3}  {it['pid']:<14} {it['genre']:<22} "
              f"rank={it['rank'] or '-'} pubs={it['pubs']} conf={it['confidence']} "
              f"tier={it['tier']}  {it['title'][:48]}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("corpus_root", type=Path)
    ap.add_argument("--table", default="mogi")
    ap.add_argument("--region", default="eu-west-1")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--skip-verify", action="store_true")
    ap.add_argument("--prune-stale", action="store_true",
                    help="delete PROBLIST/META rows whose pid is not in this corpus")
    ap.add_argument("--only", nargs="+", metavar="ID",
                    help="re-ingest just these problems (pid or bare id); never prunes")
    ap.add_argument("--show", metavar="PID", help="print one parsed problem's metadata")
    args = ap.parse_args()
    if args.only and args.prune_stale:
        sys.exit("--only and --prune-stale together would delete every other problem; refusing")

    items, skipped, stats = collect(args.corpus_root.expanduser())
    report(items, skipped, stats)
    if args.only:
        wanted = {w.lower() for w in args.only}
        items = [i for i in items if i["pid"].lower() in wanted or i["id"].lower() in wanted]
        missing = wanted - {i["pid"].lower() for i in items} - {i["id"].lower() for i in items}
        if missing:
            sys.exit(f"--only: no such problem(s): {sorted(missing)}")
        print(f"--only: {[i['pid'] for i in items]}")
    if args.show:
        it = next((i for i in items if i["pid"] == args.show), None)
        if not it:
            sys.exit(f"no such pid {args.show}")
        for k in ("pid", "id", "slug", "title", "tier", "genre", "family", "family_n", "rank",
                  "pubs", "confidence", "importance", "round", "published", "practice",
                  "link", "alt_link", "required"):
            print(f"    {k:<11} {it[k]!r}")

    if not args.skip_verify:
        if verify(items):
            sys.exit("verification failures — not uploading")
    if args.dry_run:
        biggest = max(items, key=lambda i: sum(len(str(v)) for v in i.values()))
        print(f"dry run only. largest item ≈ "
              f"{sum(len(str(v)) for v in biggest.values()) // 1024}KB ({biggest['pid']})")
        sys.exit(0)
    upload(items, args.table, args.region, args.prune_stale)
