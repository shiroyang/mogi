"""An in-memory stand-in for the mogi DynamoDB table.

The tests and the local dev API (tools/devapi.py) use it.
It runs the calls the two Lambdas make, and it rejects what DynamoDB rejects:
a reserved word used bare, a placeholder that is defined but unused, a placeholder
that is used but undefined, two paths that overlap, a float.
That second part matters. A fake that accepted everything let a bad update reach production once.

Only the expression features the Lambdas use are implemented.
Anything else raises NotImplementedError, so new code extends this file on purpose.
"""
from __future__ import annotations

import copy
import re
import threading
from decimal import Decimal
from pathlib import Path

# https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/ReservedWords.html
RESERVED = frozenset(Path(__file__).with_name("ddb_reserved_words.txt").read_text().split())
TABLE_KEYS = ("pk", "sk")
# The stack's one index: gsi1 keeps the keys plus these four attributes (INCLUDE projection).
INDEXES = {"gsi1": {"pk": "gsi1pk", "sk": "gsi1sk", "include": ("verdict", "prob", "mode", "ms")}}
_TOKEN = re.compile(r"#\w+|:\w+|[A-Za-z_]\w*|<=|>=|<>|[=,()+\-<>]")


class ValidationException(Exception):
    """boto3 raises this as a ClientError. The message follows DynamoDB's wording."""


def _to_ddb(value):
    """Store numbers the way boto3 hands them back: as Decimal. Floats are refused, as boto3 does."""
    if isinstance(value, bool) or value is None or isinstance(value, (str, bytes, Decimal)):
        return value
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        raise TypeError("Float types are not supported. Use Decimal types instead.")
    if isinstance(value, dict):
        return {k: _to_ddb(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_to_ddb(v) for v in value]
    if isinstance(value, (set, frozenset)):
        return {_to_ddb(v) for v in value}
    raise TypeError(f"Unsupported type {type(value).__name__} for a DynamoDB attribute")


def _tokens(expr: str, what: str) -> list[str]:
    toks = _TOKEN.findall(expr)
    if "".join(toks) != re.sub(r"\s+", "", expr):
        raise ValidationException(f"Invalid {what}: Syntax error; expression: {expr!r}")
    return toks


class _Scope:
    """Resolves #names and :values for one request, and checks every placeholder was used."""

    def __init__(self, names: dict | None, values: dict | None):
        if names is not None and not names:
            raise ValidationException("ExpressionAttributeNames must not be empty")
        if values is not None and not values:
            raise ValidationException("ExpressionAttributeValues must not be empty")
        self.names, self.values = names or {}, values or {}
        self.used_names: set[str] = set()
        self.used_values: set[str] = set()

    def attr(self, tok: str) -> str:
        if tok.startswith("#"):
            if tok not in self.names:
                raise ValidationException("Invalid expression: An expression attribute name used "
                                          f"in the document path is not defined; attribute name: {tok}")
            self.used_names.add(tok)
            return self.names[tok]
        if tok.startswith(":") or not re.fullmatch(r"[A-Za-z_]\w*", tok):
            raise ValidationException(f'Invalid expression: Syntax error; token: "{tok}"')
        if tok.upper() in RESERVED:
            raise ValidationException("Invalid expression: Attribute name is a reserved keyword; "
                                      f"reserved keyword: {tok}")
        return tok

    def value(self, tok: str):
        if tok not in self.values:
            raise ValidationException("Invalid expression: An expression attribute value used "
                                      f"in expression is not defined; attribute value: {tok}")
        self.used_values.add(tok)
        return _to_ddb(self.values[tok])

    def finish(self) -> None:
        unused = sorted(set(self.names) - self.used_names)
        if unused:
            raise ValidationException("Value provided in ExpressionAttributeNames unused in "
                                      f"expressions: keys: {{{', '.join(unused)}}}")
        unused = sorted(set(self.values) - self.used_values)
        if unused:
            raise ValidationException("Value provided in ExpressionAttributeValues unused in "
                                      f"expressions: keys: {{{', '.join(unused)}}}")


def _split_top(toks: list[str]) -> list[list[str]]:
    """Split on commas that are not inside parentheses."""
    parts, cur, depth = [], [], 0
    for t in toks:
        if t == "(":
            depth += 1
        elif t == ")":
            depth -= 1
        if t == "," and depth == 0:
            parts.append(cur)
            cur = []
        else:
            cur.append(t)
    parts.append(cur)
    return parts


class _Update:
    """SET path = operand [+|- operand], … REMOVE path, …  with if_not_exists(path, operand)."""

    def __init__(self, expr: str, scope: _Scope):
        self.scope = scope
        self.sets: list[tuple[str, tuple]] = []
        self.removes: list[str] = []
        toks = _tokens(expr, "UpdateExpression")
        if not toks:
            raise ValidationException("Invalid UpdateExpression: The expression can not be empty;")
        clauses: dict[str, list[str]] = {}
        current = None
        for t in toks:
            if t.upper() in ("SET", "REMOVE", "ADD", "DELETE") and (current is None or not clauses[current] or
                                                                     clauses[current][-1] not in ("=", ",", "(", "+", "-")):
                current = t.upper()
                if current in clauses:
                    raise ValidationException(f'Invalid UpdateExpression: The "{current}" section can '
                                              "only be used once in an update expression;")
                clauses[current] = []
            elif current is None:
                raise ValidationException(f'Invalid UpdateExpression: Syntax error; token: "{t}"')
            else:
                clauses[current].append(t)
        for kind in ("ADD", "DELETE"):
            if kind in clauses:
                raise NotImplementedError(f"fakeddb: the {kind} clause is not implemented")
        for part in _split_top(clauses.get("SET", [])) if "SET" in clauses else []:
            if len(part) < 3 or part[1] != "=":
                raise ValidationException(f"Invalid UpdateExpression: Syntax error; near: {' '.join(part)!r}")
            node, rest = self._value(part[2:])
            if rest:
                raise ValidationException(f'Invalid UpdateExpression: Syntax error; token: "{rest[0]}"')
            self.sets.append((scope.attr(part[0]), node))
        for part in _split_top(clauses.get("REMOVE", [])) if "REMOVE" in clauses else []:
            if len(part) != 1:
                raise ValidationException(f"Invalid UpdateExpression: Syntax error; near: {' '.join(part)!r}")
            self.removes.append(scope.attr(part[0]))
        paths = [p for p, _ in self.sets] + self.removes
        for p in paths:
            if paths.count(p) > 1:
                raise ValidationException("Invalid UpdateExpression: Two document paths overlap with each "
                                          f"other; must remove or rewrite one of these paths; path: [{p}]")
            if p in TABLE_KEYS:
                raise ValidationException("One or more parameter values were invalid: Cannot update "
                                          f"attribute {p}. This attribute is part of the key")

    def _operand(self, toks: list[str]) -> tuple[tuple, list[str]]:
        if not toks:
            raise ValidationException("Invalid UpdateExpression: Syntax error; an operand is missing")
        head = toks[0]
        if head.lower() == "if_not_exists":
            if len(toks) < 6 or toks[1] != "(" or toks[3] != ",":
                raise ValidationException("Invalid UpdateExpression: Syntax error in if_not_exists")
            inner, rest = self._operand(toks[4:])
            if not rest or rest[0] != ")":
                raise ValidationException("Invalid UpdateExpression: Syntax error in if_not_exists")
            return ("ifne", self.scope.attr(toks[2]), inner), rest[1:]
        if len(toks) > 1 and toks[1] == "(":
            raise NotImplementedError(f"fakeddb: the function {head} is not implemented")
        if head.startswith(":"):
            return ("val", self.scope.value(head)), toks[1:]
        return ("path", self.scope.attr(head)), toks[1:]

    def _value(self, toks: list[str]) -> tuple[tuple, list[str]]:
        left, rest = self._operand(toks)
        if rest and rest[0] in "+-":
            right, rest2 = self._operand(rest[1:])
            return ("arith", rest[0], left, right), rest2
        return left, rest

    def apply(self, item: dict) -> dict:
        before = item

        def ev(node):
            kind = node[0]
            if kind == "val":
                return node[1]
            if kind == "path":
                if node[1] not in before:
                    raise ValidationException("The provided expression refers to an attribute "
                                              "that does not exist in the item")
                return before[node[1]]
            if kind == "ifne":
                return before[node[1]] if node[1] in before else ev(node[2])
            a, b = ev(node[2]), ev(node[3])
            for operand in (a, b):
                if not isinstance(operand, Decimal):
                    raise ValidationException("An operand in the update expression has an incorrect data type")
            return a + b if node[1] == "+" else a - b

        after = dict(before)
        for attr, node in self.sets:   # every operand reads the item as it was before the update
            after[attr] = ev(node)
        for attr in self.removes:
            after.pop(attr, None)
        return after


class FakeTable:
    """The subset of boto3's Table resource that mogi uses."""

    def __init__(self, page_size: int | None = None):
        self._items: dict[tuple[str, str], dict] = {}
        self._lock = threading.RLock()
        self.page_size = page_size   # set it to make query() page, as DynamoDB does after 1 MB

    # ------------------------------------------------------------ helpers
    @staticmethod
    def _key(key: dict) -> tuple[str, str]:
        if set(key) != set(TABLE_KEYS):
            raise ValidationException("The provided key element does not match the schema")
        return key["pk"], key["sk"]

    @staticmethod
    def _project(item: dict, expr: str | None, scope: _Scope, allowed: tuple | None = None) -> dict:
        if expr is None:
            return copy.deepcopy(item)
        attrs = [scope.attr(part[0]) if len(part) == 1 else None
                 for part in _split_top(_tokens(expr, "ProjectionExpression"))]
        if None in attrs:
            raise ValidationException(f"Invalid ProjectionExpression: Syntax error; expression: {expr!r}")
        if allowed is not None:
            outside = [a for a in attrs if a not in allowed]
            if outside:
                raise ValidationException("One or more parameter values were invalid: the index does "
                                          f"not project the requested attributes: {outside}")
        return copy.deepcopy({a: item[a] for a in attrs if a in item})

    def all_items(self) -> list[dict]:
        with self._lock:
            return [copy.deepcopy(v) for _, v in sorted(self._items.items())]

    # ------------------------------------------------------------ item calls
    def get_item(self, Key: dict, ProjectionExpression: str | None = None,
                 ExpressionAttributeNames: dict | None = None, **kw) -> dict:
        if kw:
            raise NotImplementedError(f"fakeddb: get_item({', '.join(kw)}) is not implemented")
        scope = _Scope(ExpressionAttributeNames, None)
        if ExpressionAttributeNames is not None and ProjectionExpression is None:
            raise ValidationException("ExpressionAttributeNames can only be specified when using expressions")
        with self._lock:
            item = self._items.get(self._key(Key))
            if item is None:
                if ProjectionExpression is not None:   # still validate the expression
                    self._project({}, ProjectionExpression, scope)
                    scope.finish()
                return {}
            out = self._project(item, ProjectionExpression, scope)
        scope.finish()
        return {"Item": out}

    def put_item(self, Item: dict, **kw) -> dict:
        if kw:
            raise NotImplementedError(f"fakeddb: put_item({', '.join(kw)}) is not implemented")
        for k in TABLE_KEYS:
            if not isinstance(Item.get(k), str) or not Item[k]:
                raise ValidationException(f"One or more parameter values were invalid: Missing the key {k} in the item")
        with self._lock:
            self._items[(Item["pk"], Item["sk"])] = _to_ddb(dict(Item))
        return {}

    def delete_item(self, Key: dict, **kw) -> dict:
        if kw:
            raise NotImplementedError(f"fakeddb: delete_item({', '.join(kw)}) is not implemented")
        with self._lock:
            self._items.pop(self._key(Key), None)
        return {}

    def update_item(self, Key: dict, UpdateExpression: str, ExpressionAttributeNames: dict | None = None,
                    ExpressionAttributeValues: dict | None = None, ReturnValues: str = "NONE", **kw) -> dict:
        if kw:
            raise NotImplementedError(f"fakeddb: update_item({', '.join(kw)}) is not implemented")
        scope = _Scope(ExpressionAttributeNames, ExpressionAttributeValues)
        update = _Update(UpdateExpression, scope)
        scope.finish()
        with self._lock:
            k = self._key(Key)
            after = update.apply(self._items.get(k) or {"pk": k[0], "sk": k[1]})
            self._items[k] = after
            out = copy.deepcopy(after)
        if ReturnValues == "ALL_NEW":
            return {"Attributes": out}
        if ReturnValues != "NONE":
            raise NotImplementedError(f"fakeddb: ReturnValues={ReturnValues} is not implemented")
        return {}

    # ------------------------------------------------------------ query
    def query(self, KeyConditionExpression: str, ExpressionAttributeValues: dict | None = None,
              ExpressionAttributeNames: dict | None = None, IndexName: str | None = None,
              ScanIndexForward: bool = True, Limit: int | None = None,
              ProjectionExpression: str | None = None, ExclusiveStartKey: dict | None = None, **kw) -> dict:
        if kw:
            raise NotImplementedError(f"fakeddb: query({', '.join(kw)}) is not implemented")
        if not isinstance(KeyConditionExpression, str):
            raise NotImplementedError("fakeddb: pass KeyConditionExpression as a string")
        if IndexName is not None and IndexName not in INDEXES:
            raise ValidationException(f"The table does not have the specified index: {IndexName}")
        pk_attr, sk_attr = (INDEXES[IndexName]["pk"], INDEXES[IndexName]["sk"]) if IndexName else TABLE_KEYS
        scope = _Scope(ExpressionAttributeNames, ExpressionAttributeValues)
        toks = _tokens(KeyConditionExpression, "KeyConditionExpression")
        if len(toks) < 3 or toks[1] != "=":
            raise ValidationException("Invalid KeyConditionExpression: the partition key needs an equality")
        if scope.attr(toks[0]) != pk_attr:
            raise ValidationException(f"Query condition missed key schema element: {pk_attr}")
        pk_value = scope.value(toks[2])
        rest = toks[3:]
        sk_test = lambda s: True  # noqa: E731
        if rest:
            if rest[0].upper() != "AND":
                raise ValidationException(f'Invalid KeyConditionExpression: Syntax error; token: "{rest[0]}"')
            cond = rest[1:]
            if len(cond) == 6 and cond[0].lower() == "begins_with" and cond[1] == "(" and cond[3] == "," and cond[5] == ")":
                attr, prefix = scope.attr(cond[2]), scope.value(cond[4])
                sk_test = lambda s: s.startswith(prefix)  # noqa: E731
            elif len(cond) == 3 and cond[1] in ("=", "<", "<=", ">", ">="):
                attr, bound, op = scope.attr(cond[0]), scope.value(cond[2]), cond[1]
                sk_test = {"=": lambda s: s == bound, "<": lambda s: s < bound, "<=": lambda s: s <= bound,
                           ">": lambda s: s > bound, ">=": lambda s: s >= bound}[op]
            elif len(cond) == 5 and cond[1].upper() == "BETWEEN" and cond[3].upper() == "AND":
                attr, lo, hi = scope.attr(cond[0]), scope.value(cond[2]), scope.value(cond[4])
                sk_test = lambda s: lo <= s <= hi  # noqa: E731
            else:
                raise ValidationException("Invalid KeyConditionExpression: unsupported sort key condition")
            if attr != sk_attr:
                raise ValidationException(f"Query key condition not supported: expected the sort key {sk_attr}")
        allowed = None
        if IndexName:
            allowed = TABLE_KEYS + (pk_attr, sk_attr) + INDEXES[IndexName]["include"]
        with self._lock:
            rows = [v for v in self._items.values()
                    if v.get(pk_attr) == pk_value and isinstance(v.get(sk_attr), str) and sk_test(v[sk_attr])]
            rows.sort(key=lambda v: (v[sk_attr], v["pk"], v["sk"]), reverse=not ScanIndexForward)
            if ExclusiveStartKey:
                marker = (ExclusiveStartKey["pk"], ExclusiveStartKey["sk"])
                at = next((i for i, v in enumerate(rows) if (v["pk"], v["sk"]) == marker), None)
                if at is None:
                    raise ValidationException("The provided starting key is invalid")
                rows = rows[at + 1:]
            cap = min(x for x in (Limit, self.page_size, len(rows)) if x is not None)
            page, more = rows[:cap], len(rows) > cap
            items = []
            for v in page:
                visible = v if allowed is None else {a: v[a] for a in allowed if a in v}
                items.append(self._project(visible, ProjectionExpression, scope, allowed if ProjectionExpression else None))
        if not page and ProjectionExpression is not None:
            self._project({}, ProjectionExpression, scope, allowed)
        scope.finish()
        out = {"Items": items, "Count": len(items), "ScannedCount": len(items)}
        if more:
            last = page[-1]
            out["LastEvaluatedKey"] = {"pk": last["pk"], "sk": last["sk"]}
        return out

    # ------------------------------------------------------------ batch
    def batch_writer(self):
        table = self

        class _Batch:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def put_item(self, Item):
                table.put_item(Item=Item)

            def delete_item(self, Key):
                table.delete_item(Key=Key)

        return _Batch()
