"""What the ingester derives from a problem: difficulty, time, and the hint ladder."""
from __future__ import annotations

import unittest

import support  # noqa: F401  (puts tools/ and backend/judge on the path)
import ingest

ALGO = """# B01 — A sample search problem

| | |
|---|---|
| **Tier** | B (algorithm) |
| **Solution** | [`x.py`](x.py) — 10 self-checks |
| **Practice** | ⭐⭐⭐ same problem — [LC 162 Find Peak Element](https://leetcode.com/problems/find-peak-element/) *Medium* · [NeetCode](https://neetcode.io/x) — mirror image |

## 1. Statement (as published)
> Find it.

## 2. Clarifying questions
1. **Empty input?** I return `-1`.

## 3. Two examples — one normal, one edge
| Input | Expected |

## 4. Brute force + its complexity
Scan every index. **O(n)**.

## 5. Approach — stated in words before any code
Binary search on the slope.

## 6. Code
```python
pass
```

## 7. Complexity + dive-deeps
- *"Why is it legal?"* → Because.
"""

DESIGN = """# A06 — A sample design problem

## 1. Statement (as published)
> Design it.

## 2. Clarifying questions — the ones worth 30 seconds
1. How many promotions?

## 3. Worked example — input → expected output
| in | out |

## 4. The growth axis
More criteria will come.

## 5. Structure choice — and the alternative I rejected
One small object per rule.

## 6. The four boxes
| Box | Class |

## 8. Hand-trace of §3  *(ritual line 1)*
Step by step.
"""


class Practice(unittest.TestCase):
    def test_keeps_the_first_twins_difficulty(self):
        row = ("⭐⭐ same core — [LC 1603 Design Parking System](https://leetcode.com/problems/design-parking-system/) "
               "*Easy* · [LC 588](https://leetcode.com/x) *Hard* — counts spots instead of assigning them")
        p = ingest.parse_practice(row)
        self.assertEqual((p["stars"], p["label"], p["difficulty"]), (2, "LC 1603 Design Parking System", "Easy"))

    def test_no_twin_means_no_difficulty(self):
        p = ingest.parse_practice("— none of LeetCode / NeetCode / HelloInterview")
        self.assertEqual((p["stars"], p["url"], p["difficulty"]), (0, "", ""))
        self.assertEqual(ingest.parse_practice("")["difficulty"], "")


class Size(unittest.TestCase):
    def test_code_loc_skips_blanks_comments_and_docstrings(self):
        src = '''"""Module docstring
spanning two lines."""
import math

# a comment
def area(r):
    """One-line docstring."""
    # inside
    return math.pi * r * r


class Box:
    """Class docstring."""

    def __init__(self, w):
        self.w = w  # trailing comments still count as code
'''
        self.assertEqual(ingest.code_loc(src), 6)   # import, def, return, class, def __init__, self.w

    def test_estimate(self):
        cases = {
            (19, "Easy"): ("Easy", "twin", 15),
            (19, "Medium"): ("Medium", "twin", 15),
            (30, "Medium"): ("Medium", "twin", 30),
            (34, "Hard"): ("Hard", "twin", 30),
            (64, "Hard"): ("Hard", "twin", 45),
            (57, "Medium"): ("Medium", "twin", 30),
            (111, "Easy"): ("Medium", "twin+size", 45),      # an Easy twin, but a full design problem here
            (332, "Easy"): ("Hard", "twin+size", 60),
            (182, "Medium"): ("Hard", "twin+size", 60),
            (120, "Medium"): ("Medium", "twin", 60),
            (20, ""): ("Easy", "size", 15),
            (44, ""): ("Medium", "size", 30),
            (151, ""): ("Medium", "size", 60),
            (235, ""): ("Hard", "size", 60),
        }
        for (loc, twin), want in cases.items():
            self.assertEqual(ingest.estimate(loc, twin), want, (loc, twin))


class Ladder(unittest.TestCase):
    def test_statement_split_keeps_hints_out_of_the_visible_part(self):
        visible, analysis, meta = ingest.split_statement(ALGO)
        self.assertIn("Statement (as published)", visible)
        self.assertIn("Two examples", visible)
        self.assertNotIn("Clarifying questions", visible)
        self.assertNotIn("Brute force", visible)
        self.assertIn("Clarifying questions", analysis)
        self.assertEqual(meta["title"], "A sample search problem")
        self.assertEqual(ingest.parse_practice(meta["practice"])["difficulty"], "Medium")

    def test_algorithm_ladder(self):
        _, analysis, _ = ingest.split_statement(ALGO)
        ladder = ingest.hint_ladder(analysis)
        self.assertEqual([r["key"] for r in ladder], ["clarify", "brute", "approach"])
        self.assertEqual(ladder[0], {"key": "clarify", "title": "Clarifying questions",
                                     "body": "1. **Empty input?** I return `-1`."})
        self.assertEqual(ladder[2]["title"], "Approach — stated in words before any code")
        self.assertEqual(ladder[2]["body"], "Binary search on the slope.")

    def test_design_ladder_is_ordered_light_to_heavy(self):
        _, analysis, _ = ingest.split_statement(DESIGN)
        ladder = ingest.hint_ladder(analysis)
        # the file lists structure before boxes; the ladder offers the lighter hint first
        self.assertEqual([r["key"] for r in ladder], ["clarify", "growth", "boxes", "structure"])
        self.assertEqual(ladder[0]["title"], "Clarifying questions — the ones worth 30 seconds")

    def test_missing_or_empty_sections_are_left_out(self):
        self.assertEqual(ingest.hint_ladder("## 7. Complexity + dive-deeps\n- x"), [])
        self.assertEqual(ingest.hint_ladder("## 2. Clarifying questions\n\n## 4. Brute force\nScan."),
                         [{"key": "brute", "title": "Brute force", "body": "Scan."}])


CARDS_ALGO = """## 5. Approach — stated in words before any code
Binary search on the slope.

## 7. Complexity + dive-deeps
- **Time O(log n) / Space O(1)** — the window halves every step.
- **Part 2 — Time O(n)** for the scan
  that confirms the answer.
- *"Why is the first step safe?"* → It keeps one half,
  not the whole list.
- *"Now return every match"* (this is the follow-up most people get) → That is O(n). No shortcut.
- *“What if the input had repeats?”* -> The promise breaks.

## 8. Escalation ladder

| Rung | The push | Answer |
|---|---|---|
| 1 | *"Make it 2-D."* | Walk the middle column with `a|b` style steps. |
| 2 | *"Make it 2-D."* | Asked twice in the source. |

Some prose between two tables.

| Rung | The push (as asked) | Answer |
|---|---|---|
| T1 | "Millions of rows?" | Nothing changes. |
"""

CARDS_DESIGN = """## 5. Structure choice — and the alternative I rejected
One small object per rule.

## 9. Edge cases  *(ritual line 2)*

| Case | Result |
|---|---|
| Empty input | `[]` |

## 10. Complexity — stated unprompted  *(ritual line 3)*
- **`find`**: O(n · d).

## 12. Follow-up ladder

| Rung | The ask | What it tests | Where it breaks |
|---|---|---|---|
| 1 | *"Write a small class"* | Can you write four lines | `items=[]` as a default |
"""


class QuestionCards(unittest.TestCase):
    def test_an_algorithm_problem(self):
        cards = ingest.question_cards(CARDS_ALGO)
        self.assertEqual([(c["kind"], c["q"]) for c in cards], [
            ("approach", ""), ("complexity", ""),
            ("dive", "Why is the first step safe?"),
            ("dive", "Now return every match (this is the follow-up most people get)"),
            ("dive", "What if the input had repeats?"),
            ("followup", '*"Make it 2-D."*'), ("followup", '*"Make it 2-D."*'), ("followup", '"Millions of rows?"'),
        ])
        by_kind = lambda k: [c for c in cards if c["kind"] == k]  # noqa: E731
        self.assertEqual(by_kind("approach")[0]["a"], "Binary search on the slope.")
        # the costs are every bullet that is not a question, kept as a list
        self.assertEqual(by_kind("complexity")[0]["a"],
                         "- **Time O(log n) / Space O(1)** — the window halves every step.\n"
                         "- **Part 2 — Time O(n)** for the scan\n  that confirms the answer.")
        self.assertEqual(by_kind("dive")[0]["a"], "It keeps one half,\n  not the whole list.")
        self.assertEqual(by_kind("dive")[2]["a"], "The promise breaks.")
        # a stray pipe inside a code span splits the row; it is put back
        self.assertEqual(by_kind("followup")[0]["a"], "Walk the middle column with `a|b` style steps.")
        self.assertEqual(by_kind("followup")[2]["a"], "Nothing changes.")       # the second table counts too

    def test_keys_are_stable_readable_and_unique(self):
        cards = ingest.question_cards(CARDS_ALGO)
        keys = [c["key"] for c in cards]
        self.assertEqual(keys[:2], ["approach", "complexity"])
        self.assertEqual(len(set(keys)), len(keys))
        self.assertRegex(keys[2], r"^d[0-9a-f]{8}$")
        self.assertEqual(keys[6], keys[5] + "x")                                 # the same question asked twice
        self.assertTrue(all(k.isalnum() for k in keys))
        self.assertEqual(keys, [c["key"] for c in ingest.question_cards(CARDS_ALGO)])
        edited = CARDS_ALGO.replace("It keeps one half", "It keeps exactly one half")
        self.assertEqual(keys, [c["key"] for c in ingest.question_cards(edited)])  # editing an answer keeps the schedule

    def test_a_design_problem(self):
        cards = ingest.question_cards(CARDS_DESIGN)
        self.assertEqual([c["kind"] for c in cards], ["design", "complexity", "followup", "edges"])
        self.assertEqual(cards[0]["a"], "One small object per rule.")
        self.assertEqual(cards[1]["a"], "- **`find`**: O(n · d).")
        # a ladder with more than three columns: each extra column is labelled
        self.assertEqual(cards[2]["a"], "**What it tests:** Can you write four lines\n\n"
                                        "**Where it breaks:** `items=[]` as a default")
        self.assertIn("| Empty input | `[]` |", cards[3]["a"])

    def test_nothing_to_ask(self):
        self.assertEqual(ingest.question_cards(""), [])
        self.assertEqual(ingest.question_cards("## 6. Code\n```python\npass\n```"), [])


class GenresAndClassics(unittest.TestCase):
    def test_the_same_family_under_two_names_becomes_one(self):
        fold = lambda g: ingest.GENRE_ALIASES.get(g, g)  # noqa: E731
        self.assertEqual([fold(g) for g in ("stack/monotonic", "stack", "intervals / sweep", "interval/scheduling", "math/bit", "graph")],
                         ["stack", "stack", "intervals", "intervals", "math", "graph"])
        self.assertTrue(all(target not in ingest.GENRE_ALIASES for target in ingest.GENRE_ALIASES.values()))   # no chains

    def test_the_classics_path_numbers_its_parts_and_places(self):
        import json
        import tempfile
        from pathlib import Path
        selection = {"parts": [
            {"title": "First part", "problems": [{"pid": "Amazon/X1", "pattern": "Two pointers"}, {"pid": "Google/X2"}]},
            {"title": "Second part", "problems": [{"pid": "Amazon/X3", "pattern": "Heap"}]},
        ]}
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.assertEqual(ingest.load_classics(root / "classics.json"), {})         # no selection: an empty path
            self.assertEqual(ingest.classics_file(root), ingest.CLASSICS)              # none in the corpus: the one in tools/
            (root / "classics.json").write_text(json.dumps(selection), encoding="utf-8")
            self.assertEqual(ingest.classics_file(root), root / "classics.json")       # a corpus's own selection wins
            path = ingest.load_classics(ingest.classics_file(root))
        self.assertEqual(path, {"Amazon/X1": {"part": 1, "n": 1, "pattern": "Two pointers"},
                                "Google/X2": {"part": 1, "n": 2, "pattern": ""},
                                "Amazon/X3": {"part": 2, "n": 3, "pattern": "Heap"}})


class Collect(unittest.TestCase):
    def test_one_problem_end_to_end(self):
        import json
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "Amazon" / "problems").mkdir(parents=True)
            (root / "Amazon" / "solutions").mkdir()
            (root / "Amazon" / "README.md").write_text(
                "## Index by family\n\n| Family | A | B | Ids |\n|---|---|---|---|\n| **stack/monotonic** | 0 | 1 | `B99` |\n", encoding="utf-8")
            (root / "Amazon" / "problems" / "B99-sample-stack.md").write_text(ALGO.replace("# B01 — A sample search problem", "# B99 — A sample stack problem"), encoding="utf-8")
            (root / "Amazon" / "solutions" / "B99_sample_stack.py").write_text(
                "def ones(xs):\n    return [1 for _ in xs]\n\n\nif __name__ == \"__main__\":\n"
                "    assert ones([1]) == [1]\n    print(\"PASS one item\")\n    print(\"1/1 checks passed\")\n", encoding="utf-8")
            # the selection sits with the corpus, like the genre table
            (root / "classics.json").write_text(json.dumps({"parts": [
                {"title": "One", "problems": [{"pid": "Amazon/X1", "pattern": "Two pointers"}]},
                {"title": "Two", "problems": [{"pid": "Amazon/B99", "pattern": "A sample pattern"}]}]}), encoding="utf-8")
            items, skipped, _ = ingest.collect(root)
        self.assertEqual((len(items), skipped), (1, []))
        it = items[0]
        self.assertEqual((it["pid"], it["title"], it["tier"]), ("Amazon/B99", "A sample stack problem", "B"))
        self.assertEqual(it["genre"], "stack")                                   # the README says stack/monotonic
        self.assertEqual((it["classic"], it["classic_n"], it["pattern"]), (2, 2, "A sample pattern"))
        self.assertEqual((it["difficulty"], it["difficulty_src"], it["minutes"], it["loc"]), ("Medium", "twin", 15, 2))
        self.assertEqual([r["key"] for r in it["ladder"]], ["clarify", "brute", "approach"])
        self.assertEqual([c["kind"] for c in it["cards"]], ["approach", "dive"])
        row = ingest.problist_row(it)
        self.assertEqual((row["genre"], row["classic"], row["classic_n"], row["card_keys"][0]), ("stack", 2, 2, "approach"))


if __name__ == "__main__":
    unittest.main()
