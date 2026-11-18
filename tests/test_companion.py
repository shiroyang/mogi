"""The companion: an egg you pick, that hatches and grows with what you solve."""
from __future__ import annotations

import unittest
from urllib.parse import quote

from support import DESIGN_LADDER, GOOD, WRONG, backend, problem

DAY = 86400


def submit(b, pid: str, code: str = GOOD) -> dict:
    status, sub = b.call("POST", "/submit", {"pid": pid, "code": code, "mode": "submit"})
    assert status == 200, sub
    return b.call("GET", f"/submissions/{pid}/{quote(sub['sk'], safe='')}")[1]


def pond(**kw):
    return backend(
        problem("Amazon/S1", minutes=15, genre="graph", classic=1, classic_n=1, importance=20),
        problem("Amazon/S2", minutes=30, genre="graph", importance=40),
        problem("Amazon/M1", minutes=45, genre="string", classic=2, classic_n=2, importance=30),
        problem("Google/L1", minutes=60, genre="tree", importance=10, tier="A", ladder=[dict(r) for r in DESIGN_LADDER]),
        problem("Google/L2", minutes=60, genre="tree", classic=3, classic_n=3, importance=50),
        **kw)


def pet(b):
    return b.call("GET", "/companion")[1]["pet"]


class Choosing(unittest.TestCase):
    def test_without_an_egg_nothing_changes(self):
        b = pond()
        status, c = b.call("GET", "/companion")
        self.assertEqual((status, c["pet"], c["plan"]), (200, None, "all"))
        self.assertEqual(c["eggs"], [{"key": "jelly", "name": "Awa", "plan": "classics"},
                                     {"key": "shell", "name": "Tsubo", "plan": "amazon"},
                                     {"key": "kelp", "name": "Mosu", "plan": "google"}])
        self.assertEqual(c["plans"], [{"key": "classics", "total": 3, "solved": 0}, {"key": "amazon", "total": 3, "solved": 0},
                                      {"key": "google", "total": 2, "solved": 0}, {"key": "all", "total": 5, "solved": 0}])
        self.assertIsNone(b.call("GET", "/home")[1]["pet"])
        p = b.call("GET", "/problems/Amazon/S1")[1]
        self.assertTrue("pet" not in p and "xp" not in p)

    def test_picking_an_egg(self):
        b = pond()
        status, c = b.call("POST", "/companion", {"egg": "jelly"})
        self.assertEqual(status, 200)
        self.assertEqual(c["pet"], {"egg": "jelly", "name": "Awa", "plan": "classics", "hatched": False, "to_hatch": 3,
                                    "stage": 0, "xp": 0, "next_xp": None, "mood": "egg"})
        self.assertEqual((c["plan"], c["hatch_at"], c["stage_xp"], c["genres"]), ("classics", 3, [200, 600, 1500, 3500], {"solved": 0, "total": 3}))
        self.assertEqual(c["rules"], {"genre_xp": 15, "redo_xp": 5, "review_xp": 1, "sleep_days": 7})
        self.assertEqual(b.call("GET", "/home")[1]["pet"], c["pet"])
        self.assertEqual(b.call("GET", "/problems/Amazon/S1")[1]["pet"]["name"], "Awa")

    def test_the_choice_is_checked(self):
        b = pond()
        self.assertEqual(b.call("POST", "/companion", {"egg": "dragon"})[0], 400)
        self.assertEqual(b.call("POST", "/companion", {"plan": "everything"})[0], 400)
        self.assertEqual(b.call("POST", "/companion", {})[0], 400)
        self.assertEqual(b.call("POST", "/companion", {"egg": "kelp"}, headers={"x-mogi": None})[0], 403)
        self.assertIsNone(pet(b))

    def test_name_and_path_can_change_and_the_egg_can_be_put_away(self):
        b = pond()
        b.call("POST", "/companion", {"egg": "shell"})
        c = b.call("POST", "/companion", {"name": "  Pebble   the  Second, of the far tide pools  "})[1]
        self.assertEqual((c["pet"]["name"], c["pet"]["plan"]), ("Pebble the Second, of th", "amazon"))
        c = b.call("POST", "/companion", {"plan": "all", "name": ""})[1]
        self.assertEqual((c["pet"]["name"], c["pet"]["plan"], c["plan"]), ("Tsubo", "all", "all"))
        c = b.call("POST", "/companion", {"egg": ""})[1]                       # put away
        self.assertEqual((c["pet"], b.call("GET", "/home")[1]["pet"]), (None, None))
        c = b.call("POST", "/companion", {"egg": "kelp"})[1]                   # picked again: the path you chose is kept
        self.assertEqual((c["pet"]["egg"], c["pet"]["name"], c["pet"]["plan"]), ("kelp", "Mosu", "all"))


class Growing(unittest.TestCase):
    def test_what_was_solved_before_the_egg_already_counts(self):
        b = pond()
        submit(b, "Amazon/S1")
        c = b.call("POST", "/companion", {"egg": "jelly"})[1]
        self.assertEqual((c["pet"]["to_hatch"], c["pet"]["xp"], c["solved"]), (2, 30, 1))

    def test_xp_follows_the_rules(self):
        b = pond()
        b.call("POST", "/companion", {"egg": "jelly"})
        submit(b, "Amazon/S1")                                                 # 15, first graph problem: +15
        b.advance(seconds=60)
        b.call("POST", "/problems/Amazon/S2/hint", {"key": "brute"})
        submit(b, "Amazon/S2")                                                 # 30 less one hint = 24, graph again
        b.advance(seconds=60)
        for key in ("brute", "approach"):
            b.call("POST", "/problems/Amazon/M1/hint", {"key": key})
        submit(b, "Amazon/M1")                                                 # 45 less two hints = 27, first string: +15
        b.advance(seconds=60)
        b.call("POST", "/problems/Google/L1/solution")
        submit(b, "Google/L1")                                                 # read the solution: nothing yet
        c = b.call("GET", "/companion")[1]
        self.assertEqual(c["xp"], {"total": 96, "problems": 96, "reviews": 0})
        self.assertEqual((c["solved"], c["genres"], c["pet"]["hatched"], c["pet"]["stage"], c["pet"]["next_xp"]), (3, {"solved": 2, "total": 3}, True, 1, 200))
        self.assertEqual([(r["id"], r["xp"], r["size"], r["hints"], r["new_genre"]) for r in c["recent"]],
                         [("M1", 42, 45, 2, True), ("S2", 24, 30, 1, False), ("S1", 30, 15, 0, True)])
        self.assertEqual([(w["id"], w["redo_at"]) for w in c["waiting"]], [("L1", b.now() + 3 * DAY)])
        self.assertEqual(b.call("GET", "/problems/Google/L1")[1]["xp"], {"xp": 0, "pending": True})
        self.assertEqual(b.call("GET", "/problems/Amazon/M1")[1]["xp"], {"xp": 42, "size": 45, "hints": 2, "redos": 0, "new_genre": True, "pending": False})

        for key in ("approach", "complexity"):                                 # two review answers: +1 each
            b.call("POST", "/problems/Amazon/S1/card", {"key": key, "known": key == "approach"})
        self.assertEqual(b.call("GET", "/companion")[1]["xp"], {"total": 98, "problems": 96, "reviews": 2})

        b.advance(days=3)
        submit(b, "Google/L1")                                                 # the redo: 60, +5 for the redo, first tree: +15
        c = b.call("GET", "/companion")[1]
        self.assertEqual((c["xp"]["total"], c["waiting"], b.progress("Google/L1")["redos"]), (178, [], 1))
        self.assertEqual([r["id"] for r in c["recent"]], ["L1", "M1", "S2", "S1"])   # newest first, by when each was first accepted
        self.assertEqual(b.call("GET", "/problems/Google/L1")[1]["xp"], {"xp": 80, "size": 60, "hints": 0, "redos": 1, "new_genre": True, "pending": False})
        submit(b, "Google/L2")                                                 # 60, tree again
        p = pet(b)
        self.assertEqual((p["xp"], p["stage"], p["next_xp"]), (238, 2, 600))

    def test_a_struggle_pays_at_once_and_its_redo_adds_five(self):
        b = pond()
        b.call("POST", "/companion", {"egg": "kelp"})
        submit(b, "Amazon/S1")
        b.call("POST", "/problems/Amazon/S1/debrief", {"rating": "shaky"})
        self.assertEqual(pet(b)["xp"], 30)
        b.advance(days=3)
        submit(b, "Amazon/S1", WRONG)
        self.assertEqual(pet(b)["xp"], 30)
        submit(b, "Amazon/S1")
        self.assertEqual((pet(b)["xp"], b.progress("Amazon/S1")["redos"]), (35, 1))
        submit(b, "Amazon/S1")                                                 # solving it again later is not a redo
        self.assertEqual(pet(b)["xp"], 35)
        b.call("POST", "/problems/Amazon/S1/debrief", {"rating": "effort"})     # still a struggle: it comes back once more
        b.advance(days=7)
        submit(b, "Amazon/S1")
        self.assertEqual((pet(b)["xp"], b.progress("Amazon/S1")["redos"]), (40, 2))

    def test_it_hatches_at_three_and_grows_at_each_threshold(self):
        b = pond()
        game = {"egg": "shell"}
        row = lambda i, status="solved", minutes=60: {"pid": f"p{i}", "status": status, "minutes": minutes, "genre": "", "hints": 0}  # noqa: E731
        brief = lambda rows: b.api._pet(rows, {}, game)  # noqa: E731
        self.assertEqual([(brief([row(i) for i in range(n)])["hatched"], brief([row(i) for i in range(n)])["to_hatch"]) for n in (0, 2, 3)],
                         [(False, 3), (False, 1), (True, 0)])
        stages = {n: (brief([row(i) for i in range(n)])["stage"], brief([row(i) for i in range(n)])["next_xp"]) for n in (2, 3, 4, 10, 25, 59)}
        self.assertEqual(stages, {2: (0, None), 3: (1, 200), 4: (2, 600), 10: (3, 1500), 25: (4, 3500), 59: (5, None)})
        self.assertEqual(brief([row(i, minutes=None) for i in range(3)])["xp"], 90)       # a problem without a size counts as 30
        self.assertIsNone(b.api._pet([], {}, {}))
        self.assertIsNone(b.api._pet([], {}, {"egg": "dragon"}))


class Mood(unittest.TestCase):
    def test_hungry_when_reviews_are_due_asleep_after_a_week_and_never_worse(self):
        b = pond()
        b.call("POST", "/companion", {"egg": "jelly"})
        self.assertEqual(pet(b)["mood"], "egg")
        for pid in ("Amazon/S1", "Amazon/S2", "Amazon/M1"):
            submit(b, pid)
        self.assertEqual(pet(b)["mood"], "awake")
        b.advance(days=3)
        c = b.call("GET", "/companion")[1]
        self.assertEqual((c["pet"]["mood"], c["reviews_due"]), ("hungry", 12))
        self.assertEqual(b.call("GET", "/home")[1]["pet"]["mood"], "hungry")
        b.advance(days=5)                                                      # eight days since anything was done
        self.assertEqual(pet(b)["mood"], "asleep")
        self.assertEqual((pet(b)["hatched"], pet(b)["xp"]), (True, 120))        # asleep, and nothing lost
        b.call("POST", "/problems/Amazon/S1/card", {"key": "approach", "known": True})
        self.assertEqual(pet(b)["mood"], "hungry")                             # one answer wakes it; eleven are still due
        for pid in ("Amazon/S1", "Amazon/S2", "Amazon/M1"):
            for key in ("approach", "complexity", "d1111aaaa", "d2222bbbb"):
                b.call("POST", f"/problems/{pid}/card", {"key": key, "known": True})
        self.assertEqual((pet(b)["mood"], b.call("GET", "/companion")[1]["reviews_due"]), ("awake", 0))


class Path(unittest.TestCase):
    def today(self, b):
        home = b.call("GET", "/home")[1]
        return [i["pid"] for i in home["daily"]["items"]], home["next"] and home["next"]["pid"]

    def test_the_path_decides_what_today_draws_from(self):
        b = pond()
        self.assertEqual(self.today(b), (["Amazon/S1"], "Google/L2"))                    # no egg: the best short problem, the best overall
        b.call("POST", "/companion", {"egg": "shell"})                                    # the Amazon path
        self.assertEqual(self.today(b), (["Amazon/S1"], "Amazon/S2"))
        b.call("POST", "/companion", {"plan": "google"})
        self.assertEqual(self.today(b), (["Google/L2", "Google/L1"], "Google/L2"))        # nothing short on it: the budget widens
        b.call("POST", "/companion", {"plan": "classics"})
        self.assertEqual(self.today(b), (["Amazon/S1"], "Google/L2"))
        b.call("POST", "/companion", {"plan": "all"})
        self.assertEqual(self.today(b), (["Amazon/S1"], "Google/L2"))

    def test_a_finished_path_falls_back_to_everything_and_redos_still_come_first(self):
        b = pond()
        b.call("POST", "/companion", {"egg": "jelly"})                                    # the Classics path: S1, M1, L2
        for pid in ("Amazon/S1", "Amazon/M1", "Google/L2"):
            submit(b, pid)
        self.assertEqual(self.today(b), (["Amazon/S2"], "Amazon/S2"))
        self.assertEqual(b.call("GET", "/companion")[1]["plans"][0], {"key": "classics", "total": 3, "solved": 3})
        b.call("POST", "/problems/Amazon/S2/solution")                                    # off the path, and read
        b.advance(days=3)
        daily = b.call("GET", "/home")[1]["daily"]
        self.assertEqual((daily["kind"], daily["items"][0]["pid"]), ("redo", "Amazon/S2"))


if __name__ == "__main__":
    unittest.main()
