#!/usr/bin/env python3
"""Validate the judge against the whole corpus.

For every solution file: split it, then submit the reference implementation to the
judge as if it were user code — every one must come back AC. Also runs sabotage
cases on one problem (wrong answer / crash / infinite loop / syntax error) to prove
the other verdicts fire.

    python3 tools/corpus_sweep.py /path/to/真题 [A03 G07 ...]
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend" / "judge"))
from splitter import split_solution  # noqa: E402
from runner import judge  # noqa: E402


def sweep(corpus_root: Path, only: list[str]) -> int:
    files = sorted(
        p for c in ("Amazon", "Google")
        for p in (corpus_root / c / "solutions").glob("*.py")
        if not only or any(p.stem.split("_")[0] == f for f in only)
    )
    bad: list[tuple[str, str]] = []
    t0 = time.monotonic()
    for i, path in enumerate(files, 1):
        stem = path.stem
        try:
            s = split_solution(path.read_text(encoding="utf-8"))
        except Exception as e:
            bad.append((stem, f"SPLIT: {e}"))
            print(f"  {i:3}/{len(files)} SPLIT-FAIL {stem}: {e}")
            continue
        r = judge(s.reference, s.harness, s.imports,
                  required=s.required, time_limit_s=30)
        if r["verdict"] != "AC":
            bad.append((stem, f"{r['verdict']}: {r['detail']}"))
            print(f"  {i:3}/{len(files)} {r['verdict']:3} {stem}: {r['detail'][:120]}")
        elif i % 25 == 0:
            print(f"  {i:3}/{len(files)} ok … ({time.monotonic()-t0:.0f}s)")
    print(f"\nreference-as-submission: {len(files)-len(bad)}/{len(files)} AC "
          f"in {time.monotonic()-t0:.0f}s")
    if bad:
        print("failures:")
        for stem, why in bad:
            print(f"  {stem}: {why}")
    return len(bad)


def sabotage(corpus_root: Path) -> int:
    src = (corpus_root / "Amazon" / "solutions" /
           "A03_allocate_inventory_by_priority.py").read_text(encoding="utf-8")
    s = split_solution(src)
    cases = {
        "WA": s.reference + "\ndef unserved_customers(rows, inventory):\n    return ['WRONG']\n",
        "RE": "x = 1\n",  # none of the required API exists -> NameError
        "TLE": s.reference + "\nimport time as _t\n_t.sleep(999)\n",
        "CE": "def broken(:\n",
    }
    fails = 0
    for want, code in cases.items():
        r = judge(code, s.harness, s.imports, required=s.required, time_limit_s=4)
        ok = r["verdict"] == want
        fails += 0 if ok else 1
        print(f"  sabotage {want}: got {r['verdict']} ({r['detail'][:90]}) "
              f"{'✓' if ok else '✗ MISMATCH'}")

    # the RE case must locate the failure in the user's code
    r = judge("x = 1\n", s.harness, s.imports, required=s.required, time_limit_s=4)
    ok = "tests line" in (r.get("trace") or "")
    fails += 0 if ok else 1
    print(f"  trace annotation: {'✓' if ok else '✗ no located frames'} "
          f"({(r.get('trace') or '')[:80]})")

    # LeetCode-style adapter: wrap a function-only problem's reference inside
    # class Solution (as staticmethods), delete the module-level names, expect AC.
    for c in ("Amazon", "Google"):
        for p in sorted((corpus_root / c / "solutions").glob("*.py")):
            s2 = split_solution(p.read_text(encoding="utf-8"))
            import ast as _ast
            tree = _ast.parse(s2.reference)
            defs = {n.name for n in tree.body if isinstance(n, _ast.FunctionDef)}
            if s2.required and all(r_ in defs for r_ in s2.required):
                wrapped = (s2.reference
                           + "\nclass Solution:\n    pass\n"
                           + "".join(f"Solution.{n} = staticmethod({n})\ndel {n}\n"
                                     for n in s2.required))
                r = judge(wrapped, s2.harness, s2.imports,
                          required=s2.required, time_limit_s=30)
                ok = r["verdict"] == "AC"
                fails += 0 if ok else 1
                print(f"  adapter (class Solution) on {p.stem.split('_')[0]}: "
                      f"{r['verdict']} {'✓' if ok else '✗ ' + r['detail'][:80]}")
                return fails
    print("  adapter: ✗ no function-only problem found")
    return fails + 1


if __name__ == "__main__":
    root = Path(sys.argv[1]).expanduser()
    only = [a.upper() for a in sys.argv[2:]]
    print("== sabotage cases ==")
    f1 = sabotage(root)
    print("== full sweep ==")
    f2 = sweep(root, only)
    print(json.dumps({"sabotage_failures": f1, "sweep_failures": f2}))
    sys.exit(1 if (f1 or f2) else 0)
