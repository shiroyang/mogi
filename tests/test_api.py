"""The API and the judge's progress updates, run against the in-memory table.

    python3 -m unittest discover -s tests
"""
from __future__ import annotations

import unittest
from urllib.parse import quote

from support import DESIGN_LADDER, GOOD, WRONG, backend, problem

DAY = 86400


def judge(b, pid: str, code: str, mode: str = "submit") -> dict:
    status, sub = b.call("POST", "/submit", {"pid": pid, "code": code, "mode": mode})
    assert status == 200, sub
    status, res = b.call("GET", f"/submissions/{pid}/{quote(sub['sk'], safe='')}")
    assert status == 200, res
    return res


class ListAndDetail(unittest.TestCase):
    def test_rows_carry_difficulty_time_and_progress(self):
        b = backend(problem("Amazon/X1", difficulty="Medium", difficulty_src="twin+size", minutes=45, loc=120))
        status, body = b.call("GET", "/problems")
        self.assertEqual(status, 200)
        row = body["problems"][0]
        self.assertEqual((row["difficulty"], row["difficulty_src"], row["minutes"], row["loc"]), ("Medium", "twin+size", 45, 120))
        self.assertEqual((row["hints"], row["redo_at"], row["status"]), (0, None, ""))
        # every response with dates in it carries the server's clock
        self.assertEqual(body["now"], b.now())
        self.assertEqual(b.call("GET", "/problems/Amazon/X1")[1]["now"], b.now())
        self.assertEqual(b.call("GET", "/home")[1]["now"], b.now())

    def test_a_fresh_problem_keeps_every_spoiler_closed(self):
        b = backend(problem("Amazon/X1"))
        status, p = b.call("GET", "/problems/Amazon/X1")
        self.assertEqual(status, 200)
        self.assertEqual([(r["key"], r["free"], r["open"]) for r in p["ladder"]],
                         [("clarify", True, False), ("brute", False, False), ("approach", False, False)])
        self.assertTrue(all("body" not in r for r in p["ladder"]))
        for spoiler in ("analysis", "reference", "tests", "ac_code"):
            self.assertNotIn(spoiler, p)
        self.assertEqual((p["unlocked"], p["assisted"], p["redo_due"], p["hints"]), (False, False, False, 0))

    def test_rows_ingested_before_this_release_still_load(self):
        old = problem("Amazon/X1")
        for k in ("difficulty", "difficulty_src", "minutes", "loc", "ladder", "cards"):
            del old[k]
        b = backend()
        b.table.put_item(Item={"pk": "PROB#Amazon/X1", "sk": "META", **old})
        b.table.put_item(Item={"pk": "PROBLIST", "sk": "Amazon/X1", "id": "X1", "title": "t", "corpus": "Amazon",
                               "tier": "B", "genre": "array", "importance": 30})
        status, p = b.call("GET", "/problems/Amazon/X1")
        self.assertEqual((status, p["ladder"], p["difficulty"], p["minutes"]), (200, [], "", 0))
        status, home = b.call("GET", "/home")
        self.assertEqual((status, home["daily"]["items"][0]["pid"]), (200, "Amazon/X1"))


class Hints(unittest.TestCase):
    def test_asking_the_interviewer_is_free_and_hints_open_in_order(self):
        b = backend(problem("Amazon/X1"))
        status, p = b.call("POST", "/problems/Amazon/X1/hint", {"key": "clarify"})
        self.assertEqual(status, 200)
        self.assertEqual(p["hints"], 0)
        self.assertEqual(p["ladder"][0]["body"], "1. **Empty input?** Return 0.")
        self.assertNotIn("body", p["ladder"][1])

        status, err = b.call("POST", "/problems/Amazon/X1/hint", {"key": "approach"})
        self.assertEqual((status, err["error"]), (409, "open hint 1 first"))

        status, p = b.call("POST", "/problems/Amazon/X1/hint", {"key": "brute"})
        self.assertEqual((status, p["hints"], p["ladder"][1]["open"], p["ladder"][2]["open"]), (200, 1, True, False))
        status, p = b.call("POST", "/problems/Amazon/X1/hint", {"key": "brute"})   # again: no double count
        self.assertEqual(p["hints"], 1)
        status, p = b.call("POST", "/problems/Amazon/X1/hint", {"key": "approach"})
        self.assertEqual((p["hints"], p["ladder"][2]["body"]), (2, "Use a hash map."))
        self.assertFalse(p["unlocked"])            # hints never open the solution
        self.assertNotIn("reference", p)
        self.assertEqual(b.call("GET", "/problems")[1]["problems"][0]["hints"], 2)

    def test_design_problems_have_three_hints(self):
        b = backend(problem("Amazon/A1", tier="A", ladder=[dict(r) for r in DESIGN_LADDER]))
        for n, key in enumerate(("growth", "boxes", "structure"), 1):
            status, p = b.call("POST", "/problems/Amazon/A1/hint", {"key": key})
            self.assertEqual((status, p["hints"]), (200, n))

    def test_unknown_hint_and_unknown_problem(self):
        b = backend(problem("Amazon/X1"))
        self.assertEqual(b.call("POST", "/problems/Amazon/X1/hint", {"key": "nope"})[0], 404)
        self.assertEqual(b.call("POST", "/problems/Amazon/ZZ/hint", {"key": "clarify"})[0], 404)
        self.assertEqual(b.call("POST", "/problems/Amazon/ZZ/solution")[0], 404)

    def test_opening_a_hint_counts_as_working_on_the_problem(self):
        b = backend(problem("Amazon/X1"), problem("Amazon/X2"), problem("Amazon/X3"))
        b.call("POST", "/problems/Amazon/X2/hint", {"key": "clarify"})
        self.assertEqual(b.call("GET", "/home")[1]["last"]["pid"], "Amazon/X2")


class SolutionAndRedo(unittest.TestCase):
    def test_reading_the_solution_schedules_a_redo(self):
        b = backend(problem("Amazon/X1"), problem("Amazon/X2", importance=10))
        status, p = b.call("POST", "/problems/Amazon/X1/solution")
        self.assertEqual(status, 200)
        self.assertEqual((p["unlocked"], p["assisted"], p["redo_due"], p["solved"]), (True, True, False, False))
        self.assertEqual(p["redo_at"], b.now() + 3 * DAY)
        self.assertEqual(p["reference"], GOOD)
        self.assertTrue(all(r["open"] for r in p["ladder"]))
        self.assertEqual(p["hints"], 0)                       # reading the solution is not a hint

        # it rests: nothing sends you back to it until the redo is due
        home = b.call("GET", "/home")[1]
        self.assertEqual([i["pid"] for i in home["daily"]["items"]], ["Amazon/X2"])
        self.assertEqual(home["next"]["pid"], "Amazon/X2")
        self.assertIsNone(b.call("GET", "/problems/Amazon/X2")[1]["next"])

        # asking again while it is open changes nothing
        again = b.call("POST", "/problems/Amazon/X1/solution")[1]
        self.assertEqual(again["redo_at"], p["redo_at"])
        self.assertEqual(b.progress("Amazon/X1")["peeks"], 1)

    def test_on_the_redo_day_the_solution_closes_and_today_asks_for_it(self):
        b = backend(problem("Amazon/X1"), problem("Amazon/X2"))
        b.call("POST", "/problems/Amazon/X1/solution")
        b.advance(days=3)
        p = b.call("GET", "/problems/Amazon/X1")[1]
        self.assertEqual((p["unlocked"], p["assisted"], p["redo_due"]), (False, True, True))
        self.assertNotIn("reference", p)
        daily = b.call("GET", "/home")[1]["daily"]
        self.assertEqual((daily["kind"], daily["due"], daily["items"][0]["pid"]), ("redo", 1, "Amazon/X1"))

    def test_an_accepted_redo_clears_it_for_good(self):
        b = backend(problem("Amazon/X1"))
        b.call("POST", "/problems/Amazon/X1/solution")
        b.advance(days=3, seconds=5)
        self.assertEqual(judge(b, "Amazon/X1", WRONG)["verdict"], "WA")
        self.assertTrue(b.call("GET", "/problems/Amazon/X1")[1]["redo_due"])     # a wrong answer changes nothing
        self.assertEqual(judge(b, "Amazon/X1", GOOD)["verdict"], "AC")
        p = b.call("GET", "/problems/Amazon/X1")[1]
        self.assertEqual((p["solved"], p["assisted"], p["redo_due"], p["unlocked"]), (True, False, False, True))
        prog = b.progress("Amazon/X1")
        self.assertNotIn("redo_at", prog)
        self.assertEqual(prog["redo_done_at"], b.now())
        self.assertEqual(p["ac_code"], GOOD)

    def test_accepted_before_the_redo_day_still_comes_back(self):
        b = backend(problem("Amazon/X1"))
        b.call("POST", "/problems/Amazon/X1/solution")
        self.assertEqual(judge(b, "Amazon/X1", GOOD)["verdict"], "AC")     # typed in with the solution open
        p = b.call("GET", "/problems/Amazon/X1")[1]
        self.assertEqual((p["solved"], p["assisted"], p["unlocked"]), (True, True, True))
        b.advance(days=4)
        p = b.call("GET", "/problems/Amazon/X1")[1]
        self.assertEqual((p["solved"], p["redo_due"], p["unlocked"]), (True, True, False))
        self.assertNotIn("ac_code", p)                                      # your old answer is a spoiler too
        self.assertEqual(b.call("GET", "/home")[1]["daily"]["kind"], "redo")

    def test_peeking_during_a_redo_restarts_the_wait(self):
        b = backend(problem("Amazon/X1"))
        b.call("POST", "/problems/Amazon/X1/solution")
        b.advance(days=5)
        status, p = b.call("POST", "/problems/Amazon/X1/solution")
        self.assertEqual((status, p["unlocked"], p["redo_due"]), (200, True, False))
        self.assertEqual(p["redo_at"], b.now() + 3 * DAY)
        self.assertEqual(b.progress("Amazon/X1")["peeks"], 2)
        self.assertEqual(judge(b, "Amazon/X1", GOOD)["verdict"], "AC")     # not a redo: the solution was open
        self.assertTrue(b.call("GET", "/problems/Amazon/X1")[1]["assisted"])

    def test_a_clean_solve_never_gets_a_redo(self):
        b = backend(problem("Amazon/X1"))
        self.assertEqual(judge(b, "Amazon/X1", GOOD)["verdict"], "AC")
        status, p = b.call("POST", "/problems/Amazon/X1/solution")          # already open: nothing to mark
        self.assertEqual((status, p["assisted"], p["unlocked"]), (200, False, True))
        self.assertNotIn("redo_at", b.progress("Amazon/X1"))


class Daily(unittest.TestCase):
    def rows(self, b):
        return b.call("GET", "/problems")[1]["problems"]

    def test_while_starting_out_today_is_the_best_short_problem(self):
        b = backend(problem("Amazon/BIG", minutes=60, importance=93, difficulty="Medium"),
                    problem("Amazon/S1", minutes=15, importance=40),
                    problem("Amazon/S2", minutes=15, importance=44),
                    problem("Amazon/M1", minutes=30, importance=80))
        home = b.call("GET", "/home")[1]
        daily = home["daily"]
        self.assertEqual((daily["kind"], daily["why"], daily["budget"]), ("pick", "start", 15))
        self.assertEqual([i["pid"] for i in daily["items"]], ["Amazon/S2", "Amazon/S1"])
        self.assertEqual(daily["items"][0]["minutes"], 15)
        self.assertEqual(home["next"]["pid"], "Amazon/BIG")       # the highest ranked one is still offered

    def test_your_stars_outrank_importance_inside_the_budget(self):
        b = backend(problem("Amazon/S1", importance=40), problem("Amazon/S2", importance=44))
        b.call("PUT", "/problems/Amazon/S1/meta", {"priority": 2})
        self.assertEqual(b.call("GET", "/home")[1]["daily"]["items"][0]["pid"], "Amazon/S1")

    def test_the_budget_widens_when_nothing_short_is_left(self):
        b = backend(problem("Amazon/M1", minutes=45, importance=10), problem("Amazon/L1", minutes=60, importance=90))
        daily = b.call("GET", "/home")[1]["daily"]
        self.assertEqual((daily["budget"], [i["pid"] for i in daily["items"]]), (45, ["Amazon/M1"]))

    def test_budget_grows_with_solved_and_shrinks_after_a_break(self):
        b = backend()
        row = lambda pid, minutes, status="": {"pid": pid, "id": pid, "title": pid, "genre": "g", "importance": 10,  # noqa: E731
                                               "priority": 0, "status": status, "minutes": minutes}
        solved = lambda n: [row(f"done{i}", 15, "solved") for i in range(n)]  # noqa: E731
        open_ = [row("s", 15), row("m", 30), row("l", 45)]
        now = 1_800_000_000
        pick = lambda n, last: b.api._daily(solved(n) + open_, last, now)  # noqa: E731
        self.assertEqual((pick(0, None)["why"], pick(0, None)["budget"]), ("start", 15))
        self.assertEqual((pick(2, now)["why"], pick(2, now)["budget"]), ("start", 15))
        self.assertEqual((pick(3, now - DAY)["why"], pick(3, now - DAY)["budget"]), ("ramp", 30))
        self.assertEqual(pick(12, now - DAY)["budget"], 45)
        self.assertEqual((pick(12, now - 15 * DAY)["why"], pick(12, now - 15 * DAY)["budget"]), ("back", 15))
        self.assertEqual([i["pid"] for i in pick(3, now - DAY)["items"]], ["m", "s"])

    def test_nothing_left_gives_an_empty_pick(self):
        b = backend(problem("Amazon/X1"))
        judge(b, "Amazon/X1", GOOD)
        daily = b.call("GET", "/home")[1]["daily"]
        self.assertEqual((daily["kind"], daily["items"]), ("pick", []))

    def test_home_and_the_problem_page_agree_on_ties(self):
        b = backend(*(problem(f"Amazon/T{i}", importance=93, minutes=60) for i in (3, 1, 2)))
        home = b.call("GET", "/home")[1]
        self.assertEqual((home["next"]["pid"], home["next2"]["pid"]), ("Amazon/T1", "Amazon/T2"))
        self.assertEqual(b.call("GET", "/problems/Amazon/T1")[1]["next"]["pid"], "Amazon/T2")
        self.assertEqual(b.call("GET", "/problems/Amazon/T3")[1]["next"]["pid"], "Amazon/T1")


class JudgeAndWrites(unittest.TestCase):
    def test_run_then_wrong_then_accepted(self):
        b = backend(problem("Amazon/X1"))
        res = judge(b, "Amazon/X1", WRONG, mode="run")
        # double(2) passes by luck (2 + 2), double(0) does not
        self.assertEqual((res["verdict"], res["passed"], res["cases"][-1]["got"], res["cases"][-1]["want"]), ("WA", 1, "2", "0"))
        prog = b.progress("Amazon/X1")
        self.assertEqual((prog["runs"], prog["last_run_verdict"], prog.get("status")), (1, "WA", None))
        judge(b, "Amazon/X1", WRONG, mode="run")
        self.assertEqual(b.progress("Amazon/X1")["runs"], 2)

        self.assertEqual(judge(b, "Amazon/X1", WRONG)["verdict"], "WA")
        self.assertEqual((b.progress("Amazon/X1")["status"], b.progress("Amazon/X1")["attempts"]), ("attempted", 1))
        res = judge(b, "Amazon/X1", GOOD)
        self.assertEqual((res["verdict"], res["passed"], res["total"], res["sync"]["state"]), ("AC", 2, 2, "skipped"))
        p = b.call("GET", "/problems/Amazon/X1")[1]
        self.assertEqual((p["solved"], p["attempts"], p["unlocked"], p["ac_code"]), (True, 2, True, GOOD))
        self.assertEqual(b.call("GET", "/home")[1]["solved"], 1)

    def test_writes_need_the_custom_header(self):
        b = backend(problem("Amazon/X1"))
        for path, body in (("/problems/Amazon/X1/hint", {"key": "clarify"}), ("/problems/Amazon/X1/solution", None),
                           ("/submit", {"pid": "Amazon/X1", "code": GOOD, "mode": "run"})):
            status, err = b.call("POST", path, body, headers={"x-mogi": None})
            self.assertEqual((status, err["error"]), (403, "missing x-mogi header"), path)
        self.assertEqual(b.progress("Amazon/X1"), {})

    def test_requests_without_a_session_are_refused(self):
        b = backend(problem("Amazon/X1"))
        status, err = b.call("GET", "/problems", headers={"authorization": None})
        self.assertEqual((status, err["error"]), (401, "not signed in"))

    def test_categorise_patches_one_field_at_a_time(self):
        b = backend(problem("Amazon/X1"))
        self.assertEqual(b.call("PUT", "/problems/Amazon/X1/meta", {"priority": 3})[1]["priority"], 3)
        self.assertEqual(b.call("PUT", "/problems/Amazon/X1/meta", {"tags": ["redo", "weak"]})[1]["tags"], ["redo", "weak"])
        res = b.call("PUT", "/problems/Amazon/X1/meta", {"genre": "graph", "priority": 0})[1]
        self.assertEqual((res["genre"], res["genre_corpus"], res["priority"], res["tags"]), ("graph", "array", 0, ["redo", "weak"]))
        self.assertEqual(b.call("PUT", "/problems/Amazon/X1/meta", {})[0], 400)


if __name__ == "__main__":
    unittest.main()
