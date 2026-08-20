#!/usr/bin/env python3
"""Ingest the 真題 corpus into the mogi DynamoDB table.

For each problem: pair the statement .md with its solution .py, split the solution
into reference + harness (splitter.py), split the statement into the always-visible
part and the spoiler analysis, and write one META item plus one slim PROBLIST item.

    python3 tools/ingest.py /path/to/真題 --table mogi --region eu-west-1
    python3 tools/ingest.py /path/to/真題 --dry-run          # parse + report only
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend" / "judge"))
from splitter import split_solution  # noqa: E402

# Sections shown before solving. Everything else is analysis (unlocked after AC).
SAFE_SECTIONS = {
    "statement (as published)",
    "two examples — one normal, one edge",
    "worked example — input → expected output",
}
SPOILER_META_ROWS = ("solution", "structure", "growth axis")


def split_statement(md: str) -> tuple[str, str, dict]:
    """Return (visible, analysis, meta). The front-matter table rows feed meta;
    spoiler rows are dropped from the visible copy."""
    meta: dict[str, str] = {}
    title = ""
    m = re.match(r"^# (.+)$", md, re.M)
    if m:
        title = re.sub(r"^[A-Z]\d+\s*[—-]\s*", "", m.group(1)).strip()
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


def collect(corpus_root: Path) -> tuple[list[dict], list[str]]:
    items, skipped = [], []
    for corpus in ("Amazon", "Google"):
        # IDs: Amazon pairs A03-slug.md <-> A03_slug.py; Google shares the full
        # stem (C01a_B_slug). The ID is the stem up to the first - or _.
        sols = {re.split(r"[-_]", p.stem)[0]: p
                for p in (corpus_root / corpus / "solutions").glob("*.py")}
        for md_path in sorted((corpus_root / corpus / "problems").glob("*.md")):
            pid = re.split(r"[-_]", md_path.stem)[0]
            sol = sols.get(pid)
            if not sol:
                skipped.append(f"{pid}: statement without a solution file")
                continue
            visible, analysis, meta = split_statement(md_path.read_text(encoding="utf-8"))
            try:
                s = split_solution(sol.read_text(encoding="utf-8"))
            except Exception as e:
                skipped.append(f"{pid}: split failed — {e}")
                continue
            tier = (meta.get("tier", "") + " ")[0].strip()
            link_m = re.search(r"https?://\S+", meta.get("source", ""))
            items.append({
                "id": pid, "corpus": corpus, "slug": sol.stem,
                "title": meta.get("title") or pid,
                "tier": tier, "family": meta.get("family", ""),
                "round": meta.get("round tag", ""),
                "link": link_m.group(0).rstrip("|) ") if link_m else "",
                "statement": visible, "analysis": analysis,
                "reference": s.reference, "harness": s.harness,
                "imports": s.imports, "required": s.required, "stub": s.stub,
            })
    return items, skipped


def verify(items: list[dict]) -> int:
    """Run each reference through the runner to stamp the check count."""
    from runner import judge
    bad = 0
    for i, it in enumerate(items, 1):
        r = judge(it["reference"], it["harness"], it["imports"], time_limit_s=30)
        if r["verdict"] == "AC":
            it["checks"] = r["total"]
        else:
            bad += 1
            print(f"  VERIFY-FAIL {it['id']}: {r['verdict']} {r['detail'][:100]}")
        if i % 50 == 0:
            print(f"  verified {i}/{len(items)}")
    return bad


def upload(items: list[dict], table_name: str, region: str):
    import boto3
    table = boto3.resource("dynamodb", region_name=region).Table(table_name)
    with table.batch_writer() as batch:
        for it in items:
            batch.put_item(Item={"pk": f"PROB#{it['id']}", "sk": "META", **it})
            batch.put_item(Item={
                "pk": "PROBLIST", "sk": it["id"], "title": it["title"],
                "corpus": it["corpus"], "tier": it["tier"], "family": it["family"],
                "checks": it.get("checks", 0),
            })
    print(f"uploaded {len(items)} problems to {table_name} ({region})")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("corpus_root", type=Path)
    ap.add_argument("--table", default="mogi")
    ap.add_argument("--region", default="eu-west-1")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--skip-verify", action="store_true")
    args = ap.parse_args()

    items, skipped = collect(args.corpus_root.expanduser())
    print(f"parsed {len(items)} problems "
          f"({sum(1 for i in items if i['corpus'] == 'Amazon')} Amazon / "
          f"{sum(1 for i in items if i['corpus'] == 'Google')} Google)")
    for s in skipped:
        print(f"  skipped {s}")
    empty_stmt = [i["id"] for i in items if len(i["statement"]) < 200]
    if empty_stmt:
        print(f"  ⚠ thin statements (<200 chars): {empty_stmt}")

    if not args.skip_verify:
        if verify(items):
            sys.exit("verification failures — not uploading")
    if args.dry_run:
        biggest = max(items, key=lambda i: sum(len(str(v)) for v in i.values()))
        print(f"dry run only. largest item ≈ "
              f"{sum(len(str(v)) for v in biggest.values()) // 1024}KB ({biggest['id']})")
        sys.exit(0)
    upload(items, args.table, args.region)
