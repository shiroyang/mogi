"""Judge Lambda — invoked asynchronously by the API with a pending submission.

Loads the problem's harness from DynamoDB, runs the submission in a sandboxed
subprocess (see runner.py), writes the verdict onto the submission item, and — for
real submissions, not runs — updates the user's progress row.
"""
from __future__ import annotations

import os
import time

import boto3

from runner import judge
from splitter import split_solution  # noqa: F401  (kept importable for ops debugging)

TABLE = os.environ["TABLE"]
ddb = boto3.resource("dynamodb").Table(TABLE)


def _now() -> int:
    """The clock for progress data. One place, so tests and the dev server can move it."""
    return int(time.time())


def lambda_handler(event, _ctx):
    prob_id = event.get("pid") or event["prob"]  # corpus-qualified, e.g. Amazon/A16
    sub_sk = event["sub_sk"]
    user = event["user"]
    mode = event.get("mode", "submit")
    code = event["code"]

    meta = ddb.get_item(Key={"pk": f"PROB#{prob_id}", "sk": "META"}).get("Item")
    if not meta:
        _finish(prob_id, sub_sk, {"verdict": "XX", "passed": 0, "total": None,
                                  "ms": 0, "detail": "problem not found",
                                  "stdout": "", "stderr": ""})
        return {"ok": False}

    result = judge(
        code, meta["harness"], meta.get("imports", ""),
        required=[str(r) for r in meta.get("required", [])],
        time_limit_s=int(meta.get("time_limit_s", 20)),
    )
    _finish(prob_id, sub_sk, result)

    if mode == "submit":
        _update_progress(user, prob_id, sub_sk, result, event.get("elapsed_s"))
    else:  # a run is still "working on it" — the home page's Continue tile keys off last_at
        # Run rows expire after an hour, so the count of runs is kept here.
        ddb.update_item(
            Key={"pk": f"USER#{user}", "sk": f"PROG#{prob_id}"},
            UpdateExpression=("SET last_at=:now, last_run_verdict=:v, "
                              "#runs=if_not_exists(#runs,:z)+:one"),
            ExpressionAttributeNames={"#runs": "runs"},
            ExpressionAttributeValues={":now": _now(), ":v": result["verdict"],
                                       ":z": 0, ":one": 1},
        )
    return {"ok": True, "verdict": result["verdict"]}


def _finish(prob_id: str, sub_sk: str, r: dict):
    import json
    cases = r.get("cases", [])
    cases_json = json.dumps(cases, ensure_ascii=False)
    while len(cases_json) > 12_000 and cases:  # keep the failing tail
        cases = cases[max(1, len(cases) // 2):]
        cases_json = json.dumps(cases, ensure_ascii=False)
    ddb.update_item(
        Key={"pk": f"SUB#{prob_id}", "sk": sub_sk},
        UpdateExpression=("SET verdict=:v, passed=:p, #tot=:t, ms=:ms, detail=:d, "
                          "stdout_tail=:o, #tr=:tr, cases_json=:c, judged_at=:ts"),
        ExpressionAttributeNames={"#tot": "total", "#tr": "trace"},
        ExpressionAttributeValues={
            ":v": r["verdict"], ":p": r["passed"], ":t": r["total"] or 0,
            ":ms": r["ms"], ":d": r["detail"][:1000],
            ":o": r.get("user_stdout", "")[:4000],
            ":tr": r.get("trace", ""), ":c": cases_json, ":ts": int(time.time()),
        },
    )


def _update_progress(user: str, prob_id: str, sub_sk: str, r: dict, elapsed=None):
    now = _now()
    if r["verdict"] == "AC":
        key = {"pk": f"USER#{user}", "sk": f"PROG#{prob_id}"}
        sets = ["#st=:solved", "attempts=if_not_exists(attempts,:z)+:one", "last_at=:now",
                "solved_at=if_not_exists(solved_at,:now)", "best_ms=:ms", "ac_sub=:sk"]
        removes: list[str] = []
        names = {"#st": "status"}
        values = {":solved": "solved", ":z": 0, ":one": 1, ":now": now, ":ms": r["ms"], ":sk": sub_sk}
        if elapsed is not None:
            # how long the page's clock ran: kept for the first accepted solve, and for the latest
            sets += ["#first=if_not_exists(#first,:el)", "#latest=:el"]
            names.update({"#first": "solve_s", "#latest": "last_solve_s"})
            values[":el"] = int(elapsed)
        # A redo date is on the row when you read the solution, or rated the solve a struggle.
        # An accepted submission on or after that date is the redo, written without the
        # solution in view. It clears the date, and the rating, so the debrief asks again.
        # An earlier one leaves everything in place.
        redo_at = ddb.get_item(Key=key, ProjectionExpression="#redo",
                               ExpressionAttributeNames={"#redo": "redo_at"}).get("Item", {}).get("redo_at")
        if redo_at and redo_at <= now:
            sets += ["#done=:now", "#redos=if_not_exists(#redos,:z)+:one"]   # redos: how many times you came back to it
            removes += ["#redo", "#why", "#rating", "#rated"]
            names.update({"#done": "redo_done_at", "#redos": "redos", "#redo": "redo_at", "#why": "redo_why",
                          "#rating": "rating", "#rated": "rated_at"})
        expr = "SET " + ", ".join(sets) + (" REMOVE " + ", ".join(removes) if removes else "")
        ddb.update_item(Key=key, UpdateExpression=expr, ExpressionAttributeNames=names,
                        ExpressionAttributeValues=values)
    else:
        ddb.update_item(
            Key={"pk": f"USER#{user}", "sk": f"PROG#{prob_id}"},
            UpdateExpression=("SET #st=if_not_exists(#st,:att), "
                              "attempts=if_not_exists(attempts,:z)+:one, last_at=:now"),
            ExpressionAttributeNames={"#st": "status"},
            ExpressionAttributeValues={":att": "attempted", ":z": 0, ":one": 1, ":now": now},
        )
