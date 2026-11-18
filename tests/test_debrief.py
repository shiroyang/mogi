"""After an accepted solve: the debrief, the question cards and the review queue."""
from __future__ import annotations

import unittest
from urllib.parse import quote

from support import ALGO_CARDS, GOOD, WRONG, backend, problem

DAY = 86400


def submit(b, pid: str, code: str = GOOD, mode: str = "submit", **extra) -> dict:
    status, sub = b.call("POST", "/submit", {"pid": pid, "code": code, "mode": mode, **extra})
    assert status == 200, sub
    return b.call("GET", f"/submissions/{pid}/{quote(sub['sk'], safe='')}")[1]


def solved(*pids: str, **kw):
    b = backend(*(problem(p) for p in pids), **kw)
    for p in pids:
        assert submit(b, p)["verdict"] == "AC"
    return b


class Cards(unittest.TestCase):
    def test_cards_arrive_with_the_solve_and_not_before(self):
        b = backend(problem("Amazon/X1"))
        self.assertNotIn("cards", b.call("GET", "/problems/Amazon/X1")[1])
        b.call("POST", "/problems/Amazon/X1/solution")                 # reading the solution is not solving
        self.assertNotIn("cards", b.call("GET", "/problems/Amazon/X1")[1])
        submit(b, "Amazon/X1")
        cards = b.call("GET", "/problems/Amazon/X1")[1]["cards"]
        self.assertEqual([c["key"] for c in cards], [c["key"] for c in ALGO_CARDS])
        self.assertEqual(cards[2], {"key": "d1111aaaa", "kind": "dive", "q": "Why not sort first?",
                                    "a": "Sorting costs O(n log n).", "reps": 0, "ivl": 0, "due": None})

    def test_knew_it_climbs_the_intervals_and_not_yet_starts_over(self):
        b = solved("Amazon/X1")
        grade = lambda known: b.call("POST", "/problems/Amazon/X1/card", {"key": "d1111aaaa", "known": known})[1]  # noqa: E731
        got = [grade(True)["ivl"] for _ in range(6)]
        self.assertEqual(got, [3, 7, 16, 35, 90, 90])
        miss = grade(False)
        self.assertEqual((miss["ivl"], miss["lapses"], miss["reps"], miss["due"]), (1, 1, 7, b.now() + DAY))
        self.assertEqual(grade(True)["ivl"], 3)
        card = next(c for c in b.call("GET", "/problems/Amazon/X1")[1]["cards"] if c["key"] == "d1111aaaa")
        self.assertEqual((card["reps"], card["ivl"], card["due"]), (8, 3, b.now() + 3 * DAY))

    def test_grades_are_checked(self):
        b = backend(problem("Amazon/X1"))
        card = {"key": "d1111aaaa", "known": True}
        self.assertEqual(b.call("POST", "/problems/Amazon/X1/card", card), (409, {"error": "solve the problem first"}))
        submit(b, "Amazon/X1")
        self.assertEqual(b.call("POST", "/problems/Amazon/X1/card", {"key": "nope", "known": True})[0], 404)
        self.assertEqual(b.call("POST", "/problems/Amazon/ZZ/card", card)[0], 404)
        self.assertEqual(b.call("POST", "/problems/Amazon/X1/card", {"key": "d1111aaaa", "known": "yes"})[0], 400)
        self.assertEqual(b.call("POST", "/problems/Amazon/X1/card", card, headers={"x-mogi": None})[0], 403)
        self.assertEqual(b.call("POST", "/problems/Amazon/X1/card", card)[0], 200)

    def test_unanswered_cards_fall_due_three_days_after_the_solve(self):
        b = solved("Amazon/X1")
        self.assertEqual(b.call("GET", "/review")[1]["due"], 0)
        self.assertEqual(b.call("GET", "/home")[1]["review"], {"due": 0, "problems": 0})
        b.advance(days=3, seconds=-1)
        self.assertEqual(b.call("GET", "/review")[1]["due"], 0)
        b.advance(seconds=1)
        review = b.call("GET", "/review")[1]
        self.assertEqual((review["due"], review["problems"]), (4, 1))
        self.assertEqual([c["key"] for c in review["cards"]], [c["key"] for c in ALGO_CARDS])   # in the order they were written
        first = review["cards"][0]
        self.assertEqual((first["pid"], first["id"], first["title"], first["kind"], first["a"], first["reps"]),
                         ("Amazon/X1", "X1", "Title of X1", "approach", "Use a hash map.", 0))
        self.assertEqual(b.call("GET", "/home")[1]["review"], {"due": 4, "problems": 1})

    def test_a_graded_card_leaves_the_queue_until_its_day(self):
        b = solved("Amazon/X1")
        b.call("POST", "/problems/Amazon/X1/card", {"key": "d1111aaaa", "known": False})   # tomorrow
        b.call("POST", "/problems/Amazon/X1/card", {"key": "d2222bbbb", "known": True})    # in three days
        b.advance(days=1)
        self.assertEqual([c["key"] for c in b.call("GET", "/review")[1]["cards"]], ["d1111aaaa"])
        b.call("POST", "/problems/Amazon/X1/card", {"key": "d1111aaaa", "known": True})    # known now: three days out
        self.assertEqual(b.call("GET", "/review")[1]["due"], 0)
        b.advance(days=2)
        self.assertEqual(sorted(c["key"] for c in b.call("GET", "/review")[1]["cards"]),
                         ["approach", "complexity", "d2222bbbb"])

    def test_a_sitting_is_capped_and_starts_with_the_oldest(self):
        b = backend(*(problem(f"Amazon/X{i}") for i in range(1, 5)))
        for i in range(1, 5):                      # one solve per day
            submit(b, f"Amazon/X{i}")
            b.advance(days=1)
        b.advance(days=3)
        review = b.call("GET", "/review")[1]
        self.assertEqual((review["due"], review["problems"], len(review["cards"])), (16, 4, 12))
        self.assertEqual([c["pid"] for c in review["cards"]], ["Amazon/X1"] * 4 + ["Amazon/X2"] * 4 + ["Amazon/X3"] * 4)

    def test_the_problem_list_does_not_carry_card_keys(self):
        b = solved("Amazon/X1")
        self.assertNotIn("card_keys", b.call("GET", "/problems")[1]["problems"][0])
        self.assertNotIn("card_keys", b.call("GET", "/home")[1]["daily"])


class Debrief(unittest.TestCase):
    def test_the_debrief_comes_after_the_solve(self):
        b = backend(problem("Amazon/X1"))
        self.assertEqual(b.call("POST", "/problems/Amazon/X1/debrief", {"rating": "clean"}),
                         (409, {"error": "solve the problem first"}))
        submit(b, "Amazon/X1")
        self.assertEqual(b.call("POST", "/problems/Amazon/X1/debrief", {"rating": "great"})[0], 400)
        self.assertEqual(b.call("POST", "/problems/Amazon/X1/debrief", {})[0], 400)
        self.assertEqual(b.call("POST", "/problems/Amazon/X1/debrief", {"rating": "clean"}, headers={"x-mogi": None})[0], 403)
        p = b.call("GET", "/problems/Amazon/X1")[1]
        self.assertEqual((p["rating"], p["note"], p["rating_days"]), ("", "", {"effort": 7, "shaky": 3}))

    def test_a_struggle_comes_back_and_a_clean_solve_does_not(self):
        b = solved("Amazon/X1")
        status, p = b.call("POST", "/problems/Amazon/X1/debrief", {"rating": "effort"})
        self.assertEqual((status, p["rating"], p["redo_why"], p["redo_at"]), (200, "effort", "effort", b.now() + 7 * DAY))
        self.assertEqual((p["assisted"], p["unlocked"], p["redo_due"], p["solved"]), (False, True, False, True))
        p = b.call("POST", "/problems/Amazon/X1/debrief", {"rating": "shaky"})[1]
        self.assertEqual((p["redo_why"], p["redo_at"]), ("shaky", b.now() + 3 * DAY))
        row = b.call("GET", "/problems")[1]["problems"][0]
        self.assertEqual((row["redo_at"], row["redo_why"]), (b.now() + 3 * DAY, "shaky"))
        p = b.call("POST", "/problems/Amazon/X1/debrief", {"rating": "clean"})[1]      # changed my mind
        self.assertEqual((p["rating"], p["redo_at"], p["redo_why"]), ("clean", None, ""))
        self.assertNotIn("redo_why", b.progress("Amazon/X1"))

    def test_reading_the_solution_keeps_its_own_redo(self):
        b = backend(problem("Amazon/X1"))
        redo = b.call("POST", "/problems/Amazon/X1/solution")[1]["redo_at"]
        submit(b, "Amazon/X1")
        p = b.call("POST", "/problems/Amazon/X1/debrief", {"rating": "clean"})[1]
        self.assertEqual((p["rating"], p["redo_at"], p["redo_why"], p["assisted"]), ("clean", redo, "assisted", True))
        p = b.call("POST", "/problems/Amazon/X1/debrief", {"rating": "shaky"})[1]
        self.assertEqual((p["redo_at"], p["redo_why"]), (redo, "assisted"))

    def test_redo_rows_from_before_ratings_read_as_assisted(self):
        b = solved("Amazon/X1")
        b.table.update_item(Key={"pk": "USER#tester", "sk": "PROG#Amazon/X1"}, UpdateExpression="SET #r = :t",
                            ExpressionAttributeNames={"#r": "redo_at"}, ExpressionAttributeValues={":t": b.now() + DAY})
        p = b.call("GET", "/problems/Amazon/X1")[1]
        self.assertEqual((p["redo_why"], p["assisted"]), ("assisted", True))

    def test_the_redo_day_closes_the_debrief_and_the_cards(self):
        b = solved("Amazon/X1")
        b.call("POST", "/problems/Amazon/X1/debrief", {"rating": "effort", "note": "push, then paint"})
        b.advance(days=7)
        p = b.call("GET", "/problems/Amazon/X1")[1]
        self.assertEqual((p["redo_due"], p["unlocked"], p["rating"]), (True, False, "effort"))
        for hidden in ("cards", "note", "reference", "ac_code"):
            self.assertNotIn(hidden, p)
        self.assertEqual(b.call("GET", "/review")[1]["due"], 0)                          # its answers would give the redo away
        self.assertEqual(b.call("POST", "/problems/Amazon/X1/card", {"key": "approach", "known": True}),
                         (409, {"error": "the redo comes first"}))
        self.assertEqual(b.call("POST", "/problems/Amazon/X1/debrief", {"rating": "clean"}),
                         (409, {"error": "the redo comes first"}))
        daily = b.call("GET", "/home")[1]["daily"]
        self.assertEqual((daily["kind"], daily["items"][0]["pid"], daily["items"][0]["redo_why"]), ("redo", "Amazon/X1", "effort"))

    def test_an_accepted_redo_asks_how_it_went_again(self):
        b = solved("Amazon/X1")
        b.call("POST", "/problems/Amazon/X1/debrief", {"rating": "shaky", "note": "mind the empty input"})
        b.advance(days=3)
        self.assertEqual(submit(b, "Amazon/X1", WRONG)["verdict"], "WA")
        self.assertEqual(b.call("GET", "/problems/Amazon/X1")[1]["rating"], "shaky")
        self.assertEqual(submit(b, "Amazon/X1")["verdict"], "AC")
        p = b.call("GET", "/problems/Amazon/X1")[1]
        self.assertEqual((p["rating"], p["redo_at"], p["redo_why"], p["unlocked"], p["note"]),
                         ("", None, "", True, "mind the empty input"))
        prog = b.progress("Amazon/X1")
        self.assertTrue(all(k not in prog for k in ("redo_at", "redo_why", "rating", "rated_at")))
        self.assertEqual(b.call("GET", "/review")[1]["due"], 4)                          # the cards are back

    def test_the_note_is_trimmed_capped_and_removable(self):
        b = solved("Amazon/X1")
        p = b.call("POST", "/problems/Amazon/X1/debrief", {"note": "  paint on push, not on pop \n"})[1]
        self.assertEqual((p["note"], p["rating"]), ("paint on push, not on pop", ""))
        self.assertEqual(len(b.call("POST", "/problems/Amazon/X1/debrief", {"note": "x" * 5000})[1]["note"]), 1000)
        p = b.call("POST", "/problems/Amazon/X1/debrief", {"note": "   ", "rating": "clean"})[1]
        self.assertEqual((p["note"], p["rating"]), ("", "clean"))
        self.assertNotIn("note", b.progress("Amazon/X1"))


class SolveTime(unittest.TestCase):
    def test_the_first_accepted_time_is_kept_and_the_latest_is_tracked(self):
        b = backend(problem("Amazon/X1"))
        submit(b, "Amazon/X1", WRONG, elapsed_s=600)
        self.assertNotIn("solve_s", b.progress("Amazon/X1"))            # a wrong answer sets no solve time
        submit(b, "Amazon/X1", elapsed_s=900)
        p = b.call("GET", "/problems/Amazon/X1")[1]
        self.assertEqual((p["solve_s"], p["last_solve_s"], p["runs"]), (900, 900, 0))
        submit(b, "Amazon/X1", elapsed_s=240)
        p = b.call("GET", "/problems/Amazon/X1")[1]
        self.assertEqual((p["solve_s"], p["last_solve_s"]), (900, 240))

    def test_a_solve_without_a_clock_and_a_clock_left_running(self):
        b = backend(problem("Amazon/X1"), problem("Amazon/X2"))
        submit(b, "Amazon/X1")                                          # the CLI sends no time
        p = b.call("GET", "/problems/Amazon/X1")[1]
        self.assertEqual((p["solved"], p["solve_s"], p["last_solve_s"]), (True, None, None))
        submit(b, "Amazon/X2", elapsed_s=10 ** 7)                       # a tab left open all week
        self.assertEqual(b.call("GET", "/problems/Amazon/X2")[1]["solve_s"], 6 * 3600)
        status, err = b.call("POST", "/submit", {"pid": "Amazon/X2", "code": GOOD, "mode": "submit", "elapsed_s": "soon"})
        self.assertEqual((status, err["error"]), (400, "elapsed_s must be a number of seconds"))


if __name__ == "__main__":
    unittest.main()
