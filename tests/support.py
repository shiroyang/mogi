"""Shared test fixtures: a local backend and a few small problems."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for sub in ("tools", "backend/judge"):
    if str(ROOT / sub) not in sys.path:
        sys.path.insert(0, str(ROOT / sub))

from localbackend import Backend  # noqa: E402

HARNESS = '''if __name__ == "__main__":
    def check(label, got, want):
        assert got == want, f"{label}: got {got!r} want {want!r}"
        print(f"PASS  {label}")
    check("double(2)", double(2), 4)
    check("double(0)", double(0), 0)
    print("2/2 checks passed")
'''
GOOD = "def double(x):\n    return x * 2\n"
WRONG = "def double(x):\n    return x + 2\n"

ALGO_LADDER = [
    {"key": "clarify", "title": "Clarifying questions", "body": "1. **Empty input?** Return 0."},
    {"key": "brute", "title": "Brute force + its complexity", "body": "Try every pair. O(n²)."},
    {"key": "approach", "title": "Approach — stated in words before any code", "body": "Use a hash map."},
]
DESIGN_LADDER = [
    {"key": "clarify", "title": "Clarifying questions — the ones worth 30 seconds", "body": "1. How many rules?"},
    {"key": "growth", "title": "The growth axis", "body": "More rules will come."},
    {"key": "boxes", "title": "The four boxes", "body": "| Box | Class |"},
    {"key": "structure", "title": "Structure choice — and the alternative I rejected", "body": "Specification."},
]


ALGO_CARDS = [
    {"key": "approach", "kind": "approach", "q": "", "a": "Use a hash map."},
    {"key": "complexity", "kind": "complexity", "q": "", "a": "- **Time O(n) / Space O(n)**"},
    {"key": "d1111aaaa", "kind": "dive", "q": "Why not sort first?", "a": "Sorting costs O(n log n)."},
    {"key": "d2222bbbb", "kind": "dive", "q": "What if the input is a stream?", "a": "Keep a running map."},
]


def problem(pid: str, **over) -> dict:
    """One ingested problem, shaped like an item from tools/ingest.py collect()."""
    corpus, bare = pid.split("/")
    it = {
        "pid": pid, "id": bare, "corpus": corpus, "slug": f"{bare}_slug", "title": f"Title of {bare}",
        "tier": "B", "family": "array", "genre": "array", "family_n": 3, "rank": None, "round": "OA",
        "published": "2026-01-01", "confidence": 3, "pubs": 1, "importance": 30,
        "practice": {"stars": 3, "url": "https://leetcode.com/problems/x/", "label": "LC 1 X", "note": "", "difficulty": "Easy"},
        "loc": 20, "difficulty": "Easy", "difficulty_src": "twin", "minutes": 15,
        "ladder": [dict(r) for r in ALGO_LADDER], "cards": [dict(c) for c in ALGO_CARDS],
        "classic": 0, "classic_n": 0, "pattern": "",
        "link": "https://example.com/p", "alt_link": "", "solution_row": "",
        "statement": f"# {bare} — Title of {bare}\n\n## 1. Statement (as published)\nDouble it.",
        "analysis": "## 2. Clarifying questions\n1. **Empty input?** Return 0.\n\n## 4. Brute force + its complexity\nTry every pair. O(n²).",
        "reference": GOOD, "harness": HARNESS, "imports": "", "required": ["double"],
        "stub": "class Solution:\n    def double(self, x):\n        ...\n", "checks": 2, "time_limit_s": 20,
    }
    it.update(over)
    return it


def backend(*problems: dict, **kw) -> Backend:
    b = Backend(user="tester", frozen=True, **kw)
    b.seed(list(problems))
    return b
