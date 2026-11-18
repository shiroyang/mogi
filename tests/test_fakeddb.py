"""The in-memory table must refuse what DynamoDB refuses.
Otherwise a green test run says nothing about production."""
from __future__ import annotations

import unittest
from decimal import Decimal

import support  # noqa: F401
from fakeddb import FakeTable, ValidationException

KEY = {"pk": "USER#u", "sk": "PROG#p"}


class Updates(unittest.TestCase):
    def setUp(self):
        self.t = FakeTable()

    def test_set_if_not_exists_and_counters(self):
        expr = "SET #st=:s, attempts=if_not_exists(attempts,:z)+:one, solved_at=if_not_exists(solved_at,:now)"
        kw = {"ExpressionAttributeNames": {"#st": "status"},
              "ExpressionAttributeValues": {":s": "solved", ":z": 0, ":one": 1, ":now": 100}}
        self.t.update_item(Key=KEY, UpdateExpression=expr, **kw)
        kw["ExpressionAttributeValues"][":now"] = 200
        out = self.t.update_item(Key=KEY, UpdateExpression=expr, ReturnValues="ALL_NEW", **kw)["Attributes"]
        self.assertEqual((out["status"], out["attempts"], out["solved_at"]), ("solved", 2, 100))
        self.assertIsInstance(out["attempts"], Decimal)        # numbers come back as Decimal, as from boto3

    def test_set_and_remove_in_one_expression(self):
        self.t.put_item(Item={**KEY, "redo_at": 5, "keep": "x"})
        self.t.update_item(Key=KEY, UpdateExpression="SET #d=:now REMOVE #r",
                           ExpressionAttributeNames={"#d": "redo_done_at", "#r": "redo_at"},
                           ExpressionAttributeValues={":now": 9})
        self.assertEqual(self.t.get_item(Key=KEY)["Item"], {**KEY, "redo_done_at": 9, "keep": "x"})

    def test_reserved_word_used_bare_is_refused(self):
        for expr in ("SET status=:v", "SET hidden=:v", "SET #ok=:v REMOVE rank"):
            names = {"#ok": "fine"} if "#ok" in expr else None
            with self.assertRaisesRegex(ValidationException, "reserved keyword"):
                self.t.update_item(Key=KEY, UpdateExpression=expr, ExpressionAttributeNames=names,
                                   ExpressionAttributeValues={":v": 1})

    def test_unused_and_undefined_placeholders_are_refused(self):
        with self.assertRaisesRegex(ValidationException, "ExpressionAttributeNames unused"):
            self.t.update_item(Key=KEY, UpdateExpression="SET a=:v", ExpressionAttributeNames={"#x": "tags"},
                               ExpressionAttributeValues={":v": 1})
        with self.assertRaisesRegex(ValidationException, "ExpressionAttributeValues unused"):
            self.t.update_item(Key=KEY, UpdateExpression="SET a=:v", ExpressionAttributeValues={":v": 1, ":w": 2})
        with self.assertRaisesRegex(ValidationException, "attribute name used in the document path is not defined"):
            self.t.update_item(Key=KEY, UpdateExpression="SET #a=:v", ExpressionAttributeValues={":v": 1})
        with self.assertRaisesRegex(ValidationException, "attribute value used in expression is not defined"):
            self.t.update_item(Key=KEY, UpdateExpression="SET a=:missing", ExpressionAttributeValues={":v": 1})

    def test_empty_maps_overlapping_paths_keys_and_floats(self):
        with self.assertRaisesRegex(ValidationException, "must not be empty"):
            self.t.update_item(Key=KEY, UpdateExpression="REMOVE a", ExpressionAttributeValues={})
        with self.assertRaisesRegex(ValidationException, "overlap"):
            self.t.update_item(Key=KEY, UpdateExpression="SET a=:v REMOVE a", ExpressionAttributeValues={":v": 1})
        with self.assertRaisesRegex(ValidationException, "part of the key"):
            self.t.update_item(Key=KEY, UpdateExpression="SET sk=:v", ExpressionAttributeValues={":v": "x"})
        with self.assertRaises(TypeError):
            self.t.update_item(Key=KEY, UpdateExpression="SET a=:v", ExpressionAttributeValues={":v": 1.5})
        with self.assertRaisesRegex(ValidationException, "incorrect data type"):
            self.t.update_item(Key=KEY, UpdateExpression="SET a=if_not_exists(a,:s)+:one",
                               ExpressionAttributeValues={":s": "text", ":one": 1})
        with self.assertRaises(NotImplementedError):
            self.t.update_item(Key=KEY, UpdateExpression="ADD n :one", ExpressionAttributeValues={":one": 1})


class Queries(unittest.TestCase):
    def setUp(self):
        self.t = FakeTable()
        for i in range(5):
            self.t.put_item(Item={"pk": "SUB#p", "sk": f"{i:03d}#a", "verdict": "AC", "code": "x", "mode": "submit",
                                  "gsi1pk": "USER#u", "gsi1sk": f"{i:03d}#a", "prob": "p", "ms": i})
        self.t.put_item(Item={"pk": "USER#u", "sk": "PROG#p", "status": "solved"})

    def test_newest_first_with_limit_and_projection(self):
        out = self.t.query(KeyConditionExpression="pk = :p", ExpressionAttributeValues={":p": "SUB#p"},
                           ScanIndexForward=False, Limit=2, ProjectionExpression="sk, verdict, #md",
                           ExpressionAttributeNames={"#md": "mode"})
        self.assertEqual(out["Items"], [{"sk": "004#a", "verdict": "AC", "mode": "submit"},
                                        {"sk": "003#a", "verdict": "AC", "mode": "submit"}])
        self.assertEqual(out["LastEvaluatedKey"], {"pk": "SUB#p", "sk": "003#a"})

    def test_begins_with_and_paging(self):
        out = self.t.query(KeyConditionExpression="pk = :p AND begins_with(sk, :s)",
                           ExpressionAttributeValues={":p": "USER#u", ":s": "PROG#"})
        self.assertEqual([i["sk"] for i in out["Items"]], ["PROG#p"])
        paged = FakeTable(page_size=2)
        for i in range(5):
            paged.put_item(Item={"pk": "PROBLIST", "sk": f"p{i}"})
        got, start = [], None
        while True:
            kw = {"ExclusiveStartKey": start} if start else {}
            page = paged.query(KeyConditionExpression="pk = :p", ExpressionAttributeValues={":p": "PROBLIST"}, **kw)
            got += [i["sk"] for i in page["Items"]]
            start = page.get("LastEvaluatedKey")
            if not start:
                break
        self.assertEqual(got, ["p0", "p1", "p2", "p3", "p4"])

    def test_the_index_only_holds_what_it_projects(self):
        out = self.t.query(IndexName="gsi1", KeyConditionExpression="gsi1pk = :p",
                           ExpressionAttributeValues={":p": "USER#u"}, ScanIndexForward=False, Limit=1)
        self.assertEqual(out["Items"], [{"pk": "SUB#p", "sk": "004#a", "gsi1pk": "USER#u", "gsi1sk": "004#a",
                                         "verdict": "AC", "prob": "p", "mode": "submit", "ms": 4}])
        with self.assertRaisesRegex(ValidationException, "does not project"):
            self.t.query(IndexName="gsi1", KeyConditionExpression="gsi1pk = :p",
                         ExpressionAttributeValues={":p": "USER#u"}, ProjectionExpression="code")

    def test_bad_key_conditions_and_reserved_projection(self):
        with self.assertRaisesRegex(ValidationException, "missed key schema element"):
            self.t.query(KeyConditionExpression="sk = :p", ExpressionAttributeValues={":p": "x"})
        with self.assertRaisesRegex(ValidationException, "reserved keyword"):
            self.t.get_item(Key=KEY, ProjectionExpression="status")
        with self.assertRaisesRegex(ValidationException, "ExpressionAttributeNames unused"):
            self.t.get_item(Key=KEY, ProjectionExpression="pk", ExpressionAttributeNames={"#s": "status"})


if __name__ == "__main__":
    unittest.main()
