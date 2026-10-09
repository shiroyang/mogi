#!/usr/bin/env python3
"""One-off: move per-user rows from bare problem ids to corpus-qualified ids.

Problem ids used to be the corpus's bare id (`B01`). The two corpora reuse bare ids
(`C07` is both an Amazon and a Google problem), so every id is now `<Corpus>/<id>`.
Run this *after* `ingest.py --prune-stale` has written the qualified PROBLIST: each
bare id is resolved through it, and an id that exists in both corpora must be
disambiguated by hand with `--map C07=Amazon/C07`.

Rows touched: `USER#<u> / PROG#<bare>` (progress) and `SUB#<bare> / <sk>`
(submissions; their `prob` attribute is rewritten too). New rows are written first,
then the old ones deleted, so a re-run is harmless.

    python3 tools/migrate_ids.py --table mogi --region eu-west-1          # dry run
    python3 tools/migrate_ids.py --table mogi --region eu-west-1 --apply
"""
from __future__ import annotations

import argparse
import sys

import boto3


def scan_all(table, **kw) -> list[dict]:
    items, start = [], None
    while True:
        if start:
            kw["ExclusiveStartKey"] = start
        page = table.scan(**kw)
        items.extend(page["Items"])
        start = page.get("LastEvaluatedKey")
        if not start:
            return items


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--table", default="mogi")
    ap.add_argument("--region", default="eu-west-1")
    ap.add_argument("--apply", action="store_true", help="write changes (default: dry run)")
    ap.add_argument("--map", action="append", default=[], metavar="BARE=Corpus/ID",
                    help="resolve an ambiguous bare id by hand")
    args = ap.parse_args()
    table = boto3.resource("dynamodb", region_name=args.region).Table(args.table)

    qualified = [i["sk"] for i in table.query(
        KeyConditionExpression="pk = :p", ExpressionAttributeValues={":p": "PROBLIST"},
        ProjectionExpression="sk")["Items"] if "/" in i["sk"]]
    by_bare: dict[str, list[str]] = {}
    for pid in qualified:
        by_bare.setdefault(pid.split("/", 1)[1], []).append(pid)
    manual = dict(m.split("=", 1) for m in args.map)

    def resolve(bare: str) -> str:
        if bare in manual:
            return manual[bare]
        hits = by_bare.get(bare, [])
        if len(hits) == 1:
            return hits[0]
        sys.exit(f"cannot resolve bare id {bare!r}: candidates {hits} — pass --map {bare}=<Corpus>/{bare}")

    items = scan_all(table)
    moves: list[tuple[dict, dict]] = []  # (old item, new item)
    for it in items:
        pk, sk = it["pk"], it["sk"]
        if pk.startswith("USER#") and sk.startswith("PROG#") and "/" not in sk:
            new = dict(it, sk=f"PROG#{resolve(sk[5:])}")
            moves.append((it, new))
        elif pk.startswith("SUB#") and "/" not in pk:
            pid = resolve(pk[4:])
            new = dict(it, pk=f"SUB#{pid}", prob=pid)
            moves.append((it, new))

    if not moves:
        print("nothing to migrate — every per-user row already uses a qualified id")
        return 0
    for old, new in moves:
        print(f"  {old['pk']} / {old['sk']}  →  {new['pk']} / {new['sk']}")
    if not args.apply:
        print(f"dry run: {len(moves)} rows would move. Re-run with --apply.")
        return 0
    with table.batch_writer() as batch:
        for _, new in moves:
            batch.put_item(Item=new)
    with table.batch_writer() as batch:
        for old, _ in moves:
            batch.delete_item(Key={"pk": old["pk"], "sk": old["sk"]})
    print(f"moved {len(moves)} rows")
    return 0


if __name__ == "__main__":
    sys.exit(main())
