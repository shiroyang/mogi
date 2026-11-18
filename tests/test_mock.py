"""Mock rounds: a draw of unsolved problems, a clock, no hints, and a result."""
from __future__ import annotations

import random
import unittest
from urllib.parse import quote

from support import GOOD, WRONG, backend, problem

MIN = 60


def submit(b, pid: str, code: str = GOOD, mode: str = "submit") -> dict:
    status, sub = b.call("POST", "/submit", {"pid": pid, "code": code, "mode": mode})
    assert status == 200, sub
    return b.call("GET", f"/submissions/{pid}/{quote(sub['sk'], safe='')}")[1]


def corpus(**kw):
    """A small corpus with every kind of mock in it."""
    b = backend(
        problem("Amazon/C1", tier="B", round="VO", genre="graph", importance=40),
        problem("Amazon/C2", tier="B", round="unknown", genre="string", importance=30),
        problem("Amazon/C3", tier="B", round="VO", genre="graph", importance=20),
        problem("Amazon/D1", tier="A", round="VO", genre="design-other", importance=90),
        problem("Amazon/O1", tier="B", round="OA", genre="graph", importance=50),
        problem("Amazon/O2", tier="B", round="OA", genre="graph", importance=45),
        problem("Amazon/O3", tier="A", round="OA/VO", genre="string", importance=10),
        problem("Google/G1", tier="B", round="phone", genre="tree", importance=30),
        **kw)
    b.api._rng = random.Random(11)
    return b


class Setup(unittest.TestCase):
    def test_the_mock_page_lists_what_can_be_started(self):
        b = corpus()
        status, m = b.call("GET", "/mock")
        self.assertEqual((status, m["active"], m["history"]), (200, None, []))
        self.assertEqual(m["formats"], {"coding": {"count": 1, "minutes": 45, "choices": [30, 45, 60]},
                                        "design": {"count": 1, "minutes": 60, "choices": [45, 60, 90]},
                                        "oa": {"count": 2, "minutes": 90, "choices": [60, 90, 120]}})
        self.assertEqual(m["pools"], {"Amazon": {"coding": 3, "design": 1, "oa": 3}, "Google": {"coding": 1, "design": 0, "oa": 0}})
        self.assertIsNone(b.call("GET", "/home")[1]["mock"])

    def test_solved_and_resting_problems_leave_the_pool(self):
        b = corpus()
        submit(b, "Amazon/C1")
        b.call("POST", "/problems/Amazon/C2/solution")
        self.assertEqual(b.call("GET", "/mock")[1]["pools"]["Amazon"], {"coding": 1, "design": 1, "oa": 3})
        m = b.call("POST", "/mock", {"corpus": "Amazon", "format": "coding"})[1]
        self.assertEqual([p["pid"] for p in m["problems"]], ["Amazon/C3"])

    def test_starting_is_checked(self):
        b = corpus()
        self.assertEqual(b.call("POST", "/mock", {"corpus": "Amazon", "format": "quiz"})[0], 400)
        self.assertEqual(b.call("POST", "/mock", {"corpus": "Amazon", "format": "coding", "minutes": 50})[0], 400)
        self.assertEqual(b.call("POST", "/mock", {"corpus": "Amazon", "format": "coding", "minutes": True})[0], 400)
        self.assertEqual(b.call("POST", "/mock", {"corpus": "Nowhere", "format": "coding"})[0], 400)
        self.assertEqual(b.call("POST", "/mock", {"corpus": "Amazon", "format": "coding"}, headers={"x-mogi": None})[0], 403)
        self.assertEqual(b.call("POST", "/mock", {"corpus": "Google", "format": "oa"}),
                         (409, {"error": "not enough unsolved problems for this mock"}))
        self.assertEqual(b.call("POST", "/mock/end"), (409, {"error": "no mock is running"}))
        self.assertEqual(b.call("POST", "/mock", {"corpus": "Amazon", "format": "coding"})[0], 200)
        self.assertEqual(b.call("POST", "/mock", {"corpus": "Amazon", "format": "design"}),
                         (409, {"error": "a mock is already running"}))


class Draw(unittest.TestCase):
    def test_a_coding_round_is_one_untouched_algorithm_problem(self):
        seen = set()
        for seed in range(12):
            b = corpus()
            b.call("POST", "/problems/Amazon/C1/hint", {"key": "clarify"})      # C1 has been looked at
            b.api._rng = random.Random(seed)
            m = b.call("POST", "/mock", {"corpus": "Amazon", "format": "coding", "minutes": 30})[1]
            self.assertEqual((m["format"], m["corpus"], m["minutes"], m["total"], m["active"]), ("coding", "Amazon", 30, 1, True))
            self.assertEqual(m["ends_at"] - m["started_at"], 30 * MIN)
            seen.add(m["problems"][0]["pid"])
        self.assertEqual(seen, {"Amazon/C2", "Amazon/C3"})                      # random, and never the touched one

    def test_a_touched_problem_is_drawn_only_when_nothing_else_is_left(self):
        b = backend(problem("Amazon/C1", tier="B", round="VO"))
        b.call("POST", "/problems/Amazon/C1/hint", {"key": "clarify"})
        m = b.call("POST", "/mock", {"corpus": "Amazon", "format": "coding"})[1]
        self.assertEqual([p["pid"] for p in m["problems"]], ["Amazon/C1"])

    def test_an_online_assessment_is_two_problems_of_different_genres(self):
        for seed in range(8):
            b = corpus()
            b.api._rng = random.Random(seed)
            m = b.call("POST", "/mock", {"corpus": "Amazon", "format": "oa"})[1]
            pids = [p["pid"] for p in m["problems"]]
            self.assertEqual((len(pids), m["minutes"]), (2, 90))
            self.assertIn("Amazon/O3", pids)                                   # the only one that is not a graph problem
            self.assertTrue(set(pids) <= {"Amazon/O1", "Amazon/O2", "Amazon/O3"})

    def test_what_kind_of_problem_it_is_stays_hidden_until_the_end(self):
        b = corpus()
        m = b.call("POST", "/mock", {"corpus": "Amazon", "format": "design"})[1]
        self.assertEqual(m["problems"], [{"pid": "Amazon/D1", "id": "D1", "title": "Title of D1", "ac_s": None, "runs": 0, "submits": 0}])
        done = b.call("POST", "/mock/end")[1]
        self.assertEqual((done["problems"][0]["genre"], done["problems"][0]["difficulty"], done["problems"][0]["minutes"]),
                         ("design-other", "Easy", 15))


class Running(unittest.TestCase):
    def start(self, fmt="design"):
        b = corpus()
        m = b.call("POST", "/mock", {"corpus": "Amazon", "format": fmt})[1]
        return b, m, [p["pid"] for p in m["problems"]]

    def test_hints_and_the_solution_are_off_but_asking_is_allowed(self):
        b, m, (pid,) = self.start()
        self.assertEqual(b.call("POST", f"/problems/{pid}/hint", {"key": "brute"}), (409, {"error": "hints are off during a mock"}))
        self.assertEqual(b.call("POST", f"/problems/{pid}/solution"), (409, {"error": "the solution is off during a mock"}))
        status, p = b.call("POST", f"/problems/{pid}/hint", {"key": "clarify"})
        self.assertEqual((status, p["ladder"][0]["open"], p["hints"]), (200, True, 0))
        self.assertEqual(p["mock"], {"id": m["id"], "ends_at": m["ends_at"], "index": 0, "total": 1, "solved": False, "next": None})
        # a problem outside the mock is not affected
        self.assertEqual(b.call("POST", "/problems/Amazon/C1/hint", {"key": "brute"})[0], 200)
        self.assertNotIn("mock", b.call("GET", "/problems/Amazon/C1")[1])
        self.assertEqual(b.call("GET", "/home")[1]["mock"], {"id": m["id"], "ends_at": m["ends_at"], "solved": 0, "total": 1})

    def test_an_accepted_submission_ends_a_one_problem_mock(self):
        b, m, (pid,) = self.start()
        submit(b, pid, WRONG, mode="run")
        submit(b, pid, WRONG, mode="run")
        submit(b, pid, WRONG)
        running = b.call("GET", "/mock")[1]["active"]
        self.assertEqual((running["solved"], running["problems"][0]["runs"], running["problems"][0]["submits"], running["problems"][0]["ac_s"]), (0, 2, 1, None))
        self.assertEqual(submit(b, pid, mode="run")["verdict"], "AC")           # a run that passes is not a submission
        self.assertEqual(b.call("GET", "/mock")[1]["active"]["solved"], 0)
        b.advance(seconds=10 * MIN)
        self.assertEqual(submit(b, pid)["verdict"], "AC")
        page = b.call("GET", "/mock")[1]
        self.assertIsNone(page["active"])
        done = page["history"][0]
        self.assertEqual((done["id"], done["reason"], done["solved"], done["total"], done["active"]), (m["id"], "done", 1, 1, False))
        self.assertEqual((done["problems"][0]["ac_s"], done["problems"][0]["runs"], done["problems"][0]["submits"]), (600, 3, 2))
        self.assertEqual(done["ended_at"], m["started_at"] + 600)
        self.assertIsNone(b.call("GET", "/home")[1]["mock"])
        self.assertNotIn("mock", b.call("GET", f"/problems/{pid}")[1])
        self.assertEqual(b.call("GET", f"/mock/{m['id']}")[1]["problems"], done["problems"])   # the result does not drift on a later read
        self.assertEqual(b.call("GET", "/mock/0000000000000")[0], 404)

    def test_when_the_time_is_up_the_mock_is_over(self):
        b, m, (pid,) = self.start()
        submit(b, pid, WRONG)
        b.advance(seconds=60 * MIN - 1)
        self.assertTrue(b.call("GET", "/mock")[1]["active"])
        b.advance(seconds=2)
        page = b.call("GET", "/mock")[1]
        self.assertIsNone(page["active"])
        self.assertEqual((page["history"][0]["reason"], page["history"][0]["solved"], page["history"][0]["ended_at"]), ("time", 0, m["ends_at"]))
        # hints are back, and solving it now is a solve, but not the mock's
        self.assertEqual(b.call("POST", f"/problems/{pid}/hint", {"key": "brute"})[0], 200)
        self.assertEqual(submit(b, pid)["verdict"], "AC")
        done = b.call("GET", f"/mock/{m['id']}")[1]
        self.assertEqual((done["solved"], done["problems"][0]["ac_s"], done["problems"][0]["submits"]), (0, None, 1))
        self.assertTrue(b.call("GET", f"/problems/{pid}")[1]["solved"])

    def test_ending_early(self):
        b, m, (pid,) = self.start()
        b.advance(seconds=5 * MIN)
        self.assertEqual(b.call("POST", "/mock/end", headers={"x-mogi": None})[0], 403)
        status, done = b.call("POST", "/mock/end")
        self.assertEqual((status, done["reason"], done["active"], done["ended_at"], done["solved"]), (200, "ended", False, m["started_at"] + 5 * MIN, 0))
        self.assertEqual(b.call("POST", "/mock", {"corpus": "Amazon", "format": "coding"})[0], 200)   # a new one can start
        self.assertEqual([h["reason"] for h in b.call("GET", "/mock")[1]["history"]], ["ended"])

    def test_a_two_problem_mock_runs_until_both_are_solved(self):
        b, m, pids = self.start("oa")
        b.advance(seconds=20 * MIN)
        submit(b, pids[1])
        running = b.call("GET", "/mock")[1]["active"]
        self.assertEqual((running["solved"], [p["ac_s"] for p in running["problems"]]), (1, [None, 1200]))
        first = b.call("GET", f"/problems/{pids[1]}")[1]["mock"]
        self.assertEqual((first["index"], first["total"], first["solved"], first["next"]["pid"]), (1, 2, True, pids[0]))
        self.assertEqual(b.call("GET", f"/problems/{pids[0]}")[1]["mock"]["next"], None)   # nothing after this one
        b.advance(seconds=30 * MIN)
        submit(b, pids[0])
        done = b.call("GET", "/mock")[1]["history"][0]
        self.assertEqual((done["reason"], done["solved"], [p["ac_s"] for p in done["problems"]], done["ended_at"]),
                         ("done", 2, [3000, 1200], m["started_at"] + 3000))

    def test_history_is_newest_first(self):
        b = corpus()
        ids = []
        for fmt in ("coding", "design", "coding"):
            ids.append(b.call("POST", "/mock", {"corpus": "Amazon", "format": fmt})[1]["id"])
            b.advance(seconds=MIN)
            b.call("POST", "/mock/end")
            b.advance(seconds=MIN)
        self.assertEqual([h["id"] for h in b.call("GET", "/mock")[1]["history"]], ids[::-1])


class Clock(unittest.TestCase):
    def test_submissions_are_stamped_with_the_clock_the_rest_of_the_app_uses(self):
        b = corpus()
        b.advance(days=2)
        submit(b, "Amazon/C1")
        row = b.call("GET", "/problems/Amazon/C1")[1]["submissions"][0]
        self.assertEqual(row["created"], b.now())
        event = b.call("GET", "/home")[1]["events"][0]
        self.assertEqual(event["ts"] // 1000, b.now())


if __name__ == "__main__":
    unittest.main()
