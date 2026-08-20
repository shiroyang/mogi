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


def lambda_handler(event, _ctx):
    prob_id = event["prob"]
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
        _update_progress(user, prob_id, sub_sk, result)
    return {"ok": True, "verdict": result["verdict"]}


def _finish(prob_id: str, sub_sk: str, r: dict):
    ddb.update_item(
        Key={"pk": f"SUB#{prob_id}", "sk": sub_sk},
        UpdateExpression=("SET verdict=:v, passed=:p, #tot=:t, ms=:ms, detail=:d, "
                          "stdout_tail=:o, #tr=:tr, judged_at=:ts"),
        ExpressionAttributeNames={"#tot": "total", "#tr": "trace"},
        ExpressionAttributeValues={
            ":v": r["verdict"], ":p": r["passed"], ":t": r["total"] or 0,
            ":ms": r["ms"], ":d": r["detail"][:1000], ":o": r["stdout"][-4000:],
            ":tr": r.get("trace", ""), ":ts": int(time.time()),
        },
    )


def _update_progress(user: str, prob_id: str, sub_sk: str, r: dict):
    now = int(time.time())
    if r["verdict"] == "AC":
        ddb.update_item(
            Key={"pk": f"USER#{user}", "sk": f"PROG#{prob_id}"},
            UpdateExpression=("SET #st=:solved, attempts=if_not_exists(attempts,:z)+:one, "
                              "last_at=:now, solved_at=if_not_exists(solved_at,:now), "
                              "best_ms=:ms, ac_sub=:sk"),
            ExpressionAttributeNames={"#st": "status"},
            ExpressionAttributeValues={":solved": "solved", ":z": 0, ":one": 1,
                                       ":now": now, ":ms": r["ms"], ":sk": sub_sk},
        )
    else:
        ddb.update_item(
            Key={"pk": f"USER#{user}", "sk": f"PROG#{prob_id}"},
            UpdateExpression=("SET #st=if_not_exists(#st,:att), "
                              "attempts=if_not_exists(attempts,:z)+:one, last_at=:now"),
            ExpressionAttributeNames={"#st": "status"},
            ExpressionAttributeValues={":att": "attempted", ":z": 0, ":one": 1, ":now": now},
        )
