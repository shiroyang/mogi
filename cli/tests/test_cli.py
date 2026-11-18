"""Offline tests for the mogi CLI: rendering, workspace layout, id resolution, config.

    python3 -m unittest discover -s cli/tests -v
"""
from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mogi_cli import cli, config, render, workspace  # noqa: E402
from mogi_cli.api import ApiError  # noqa: E402

ROWS = [
    {"pid": "Amazon/A16", "id": "A16", "corpus": "Amazon", "title": "Design a Product Search System",
     "tier": "A", "genre": "Specification/Filter", "importance": 93, "pubs": 2, "family_n": 11,
     "priority": 0, "tags": [], "status": ""},
    {"pid": "Amazon/C07", "id": "C07", "corpus": "Amazon", "title": "Merge intervals",
     "tier": "B", "genre": "intervals / sweep", "importance": 30, "pubs": 1, "family_n": 4,
     "priority": 5, "tags": ["redo"], "status": "attempted"},
    {"pid": "Google/C07", "id": "C07", "corpus": "Google", "title": "Count valid paths",
     "tier": "B", "genre": "tree", "importance": 40, "pubs": 2, "family_n": 8,
     "priority": 0, "tags": [], "status": "solved"},
]


class FakeApi:
    def __init__(self):
        self.meta_calls = []

    def problems(self):
        return {"problems": [dict(r) for r in ROWS]}

    def problem(self, pid):
        row = next(r for r in ROWS if r["pid"] == pid)
        statement = (f"# {row['id']} — {row['title']}\n\n| | |\n|---|---|\n"
                     "| **Source** | https://example.com/p |\n"
                     "| **Practice** | ⭐⭐ same core — [LC 1 X](https://leetcode.com/problems/x/) |\n\n"
                     "---\n\n## 1. Statement (as published)\n\n> Do it.")
        return {**row, "slug": f"{row['id']}_slug", "statement": statement,
                "required": ["solve"], "stub": "class Solution:\n    def solve(self):\n        ...",
                "link": "https://example.com/p", "practice": {"stars": 2, "url": "https://leetcode.com/problems/x/",
                                                             "label": "LC 1 X", "note": "same core"}}

    def set_meta(self, pid, **fields):
        self.meta_calls.append((pid, fields))
        return {"pid": pid, "genre": fields.get("genre") or "tree", "genre_corpus": "tree",
                "priority": fields.get("priority", 0), "tags": fields.get("tags", [])}


def ctx_for(argv, api=None):
    args = cli.build_parser().parse_args(argv)
    ctx = cli.Ctx(args)
    ctx.api = api or FakeApi()
    ctx.color = False
    return ctx


class RenderTests(unittest.TestCase):
    def test_wrong_answer_shows_first_failure_with_got_want(self):
        res = {"verdict": "WA", "ms": 83, "passed": 7, "detail": "published example: got 1 want 2",
               "cases": [{"status": "pass", "label": "basic"},
                         {"status": "fail", "label": "published example", "got": "[1]", "want": "[2]",
                          "call": "check('published example', f(3), [2])"}],
               "trace": "your code line 12, in f:  return x", "stdout_tail": "debug 1"}
        out = render.format_verdict(res, ROWS[0], color=False)
        self.assertIn("Wrong Answer · 83 ms · 7 checks passed before failure", out)
        self.assertIn("✕ Case 2  published example", out)
        self.assertIn("Input    : check('published example', f(3), [2])", out)
        self.assertIn("Output   : [1]", out)
        self.assertIn("Expected : [2]", out)
        self.assertIn("your code line 12", out)
        self.assertIn("debug 1", out)
        self.assertNotIn("✓ Case 1", out)  # passes hidden unless verbose

    def test_accepted_with_sync(self):
        res = {"verdict": "AC", "ms": 60, "passed": 15, "total": 15, "cases": [],
               "sync": {"state": "done", "path": "Amazon/A16_x.py"}}
        out = render.format_verdict(res, ROWS[0], color=False)
        self.assertIn("Accepted · 60 ms · 15/15 checks", out)
        self.assertIn("synced to GitHub: Amazon/A16_x.py", out)

    def test_fit_handles_cjk_width(self):
        self.assertEqual(render.width("模擬"), 4)
        self.assertEqual(len(render.fit("abc", 5)), 5)
        self.assertTrue(render.fit("abcdefgh", 5).startswith("abcd…"))


class ResolveTests(unittest.TestCase):
    def test_unique_bare_id(self):
        self.assertEqual(ctx_for(["ls"]).resolve("a16")["pid"], "Amazon/A16")

    def test_ambiguous_bare_id_lists_both(self):
        with self.assertRaises(ApiError) as cm:
            ctx_for(["ls"]).resolve("C07")
        self.assertIn("Amazon/C07", cm.exception.msg)
        self.assertIn("Google/C07", cm.exception.msg)

    def test_qualified_pid(self):
        self.assertEqual(ctx_for(["ls"]).resolve("google/c07")["pid"], "Google/C07")

    def test_unknown(self):
        with self.assertRaises(ApiError):
            ctx_for(["ls"]).resolve("Z99")


class WorkspaceTests(unittest.TestCase):
    def test_materialize_and_find_marker(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            detail = FakeApi().problem("Amazon/A16")
            d = workspace.materialize(ws, detail)
            self.assertEqual(d, ws / "Amazon" / "A16_slug")
            self.assertTrue((d / "solution.py").exists())
            self.assertIn("class Solution", (d / "solution.py").read_text())
            md = (d / "problem.md").read_text()
            self.assertEqual(md.count("# A16 — Design a Product Search System"), 1)  # no duplicate header
            self.assertIn("`solve`", md)
            self.assertIn("LC 1 X", md)                      # the corpus table survives…
            self.assertIn("| **Genre** | Specification/Filter", md)  # …with our rows appended to it
            self.assertLess(md.index("| **Practice**"), md.index("| **Genre**"))
            self.assertLess(md.index("| **Genre**"), md.index("## 1. Statement"))
            # a statement without a table gets a synthesised header
            bare = workspace.render_problem_md({**detail, "statement": "## 1. Statement\n\n> Do it."})
            self.assertTrue(bare.startswith("# A16 — Design a Product Search System\n\n| | |"))
            # solution.py survives a re-open; marker resolves from a nested path
            (d / "solution.py").write_text("x = 1\n")
            workspace.materialize(ws, detail)
            self.assertEqual((d / "solution.py").read_text(), "x = 1\n")
            found = workspace.find_marker(d / "solution.py")
            self.assertEqual(found[1]["pid"], "Amazon/A16")
            self.assertEqual(workspace.dir_for_pid(ws, "Amazon/A16"), d)
            self.assertIsNone(workspace.dir_for_pid(ws, "Google/C07"))
            workspace.materialize(ws, detail, reset=True)
            self.assertIn("class Solution", (d / "solution.py").read_text())


class CommandTests(unittest.TestCase):
    def test_ls_sorted_by_importance_with_priority_first(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            ctx_for(["ls", "-n", "0"]).args.fn(ctx_for(["ls", "-n", "0"]))
        lines = [ln for ln in buf.getvalue().splitlines() if ln.strip()]
        ids = [ln.split()[1] for ln in lines[1:4]]
        self.assertEqual(ids, ["C07", "A16", "C07"])  # ★5 Amazon/C07 first, then 93, then 40

    def test_ls_filters(self):
        buf = io.StringIO()
        ctx = ctx_for(["ls", "--genre", "tree", "-n", "0"])
        with redirect_stdout(buf):
            ctx.args.fn(ctx)
        self.assertIn("Count valid paths", buf.getvalue())
        self.assertNotIn("Merge intervals", buf.getvalue())

    def test_tag_builds_patch(self):
        api = FakeApi()
        ctx = ctx_for(["tag", "Google/C07", "--priority", "3", "--add-tag", "weak", "--genre", "graph"], api)
        with redirect_stdout(io.StringIO()):
            ctx.args.fn(ctx)
        self.assertEqual(api.meta_calls, [("Google/C07", {"genre": "graph", "priority": 3, "tags": ["weak"]})])

    def test_pick_skips_solved_and_honours_priority(self):
        buf = io.StringIO()
        ctx = ctx_for(["pick"])
        with redirect_stdout(buf):
            ctx.args.fn(ctx)
        self.assertTrue(buf.getvalue().startswith("C07 — Merge intervals"))


class SizedApi(FakeApi):
    """Rows as the API sends them since the difficulty / time / redo fields were added."""
    EXTRA = {"Amazon/A16": {"difficulty": "Medium", "minutes": 60},
             "Amazon/C07": {"difficulty": "Medium", "minutes": 30, "redo_at": 1_900_000_000},
             "Google/C07": {"difficulty": "Easy", "minutes": 15}}

    def problems(self):
        return {"problems": [{**r, **self.EXTRA[r["pid"]]} for r in ROWS]}


class DifficultyTests(unittest.TestCase):
    def run_cli(self, argv):
        buf = io.StringIO()
        ctx = ctx_for(argv, SizedApi())
        with redirect_stdout(buf):
            ctx.args.fn(ctx)
        return buf.getvalue()

    def test_ls_shows_difficulty_and_minutes(self):
        out = self.run_cli(["ls", "-n", "0"])
        self.assertIn("Diff", out.splitlines()[0])
        row = next(ln for ln in out.splitlines() if "Design a Product Search System" in ln)
        self.assertRegex(row, r"Medium\s+60\+\s+93")

    def test_easiest_and_shortest_sorts(self):
        first = lambda out: [ln for ln in out.splitlines() if ln.strip()][1]  # noqa: E731
        self.assertIn("Count valid paths", first(self.run_cli(["ls", "-n", "0", "--sort", "easiest"])))
        self.assertIn("Count valid paths", first(self.run_cli(["ls", "-n", "0", "--sort", "shortest"])))
        self.assertIn("Merge intervals", first(self.run_cli(["ls", "-n", "0"])))   # stars still win by default

    def test_difficulty_and_redo_filters(self):
        out = self.run_cli(["ls", "-n", "0", "--difficulty", "easy"])
        self.assertIn("Count valid paths", out)
        self.assertNotIn("Merge intervals", out)
        out = self.run_cli(["ls", "-n", "0", "--status", "redo"])
        self.assertIn("Merge intervals", out)
        self.assertNotIn("Design a Product Search System", out)

    def test_pick_skips_a_problem_that_waits_for_its_redo(self):
        # Amazon/C07 has five stars but its solution was read, so it rests until the redo
        out = self.run_cli(["pick"])
        self.assertTrue(out.startswith("A16 — Design a Product Search System"), out)
        self.assertIn("Medium, 60+ min", out)

    def test_rows_without_the_new_fields_still_list(self):
        buf = io.StringIO()
        ctx = ctx_for(["ls", "-n", "0", "--sort", "easiest"])
        with redirect_stdout(buf):
            ctx.args.fn(ctx)
        self.assertIn("Merge intervals", buf.getvalue())


class ConfigTests(unittest.TestCase):
    def test_roundtrip_and_permissions(self):
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["MOGI_CONFIG"] = str(Path(tmp) / "cfg.json")
            try:
                self.assertEqual(config.load()["site"], config.DEFAULT_SITE)
                p = config.save({"site": "https://x", "token": "t", "workspace": "~/w"})
                self.assertEqual(oct(p.stat().st_mode & 0o777), "0o600")
                self.assertEqual(json.loads(p.read_text())["token"], "t")
                self.assertEqual(config.workspace(config.load()), Path("~/w").expanduser())
            finally:
                del os.environ["MOGI_CONFIG"]


if __name__ == "__main__":
    unittest.main()
