"""Run the two Lambda handlers on this machine, against the in-memory table.

boto3 is replaced by a stub while the handlers are imported, so nothing here can reach AWS.
The tests and the local dev API (tools/devapi.py) both use this.
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import threading
import time
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fakeddb import FakeTable  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class Backend:
    """The API handler and the judge handler wired to one FakeTable.

    `background=True` runs the judge on a thread, the way the API invokes the real one.
    The default runs it inline, so a test sees the verdict as soon as submit returns.
    `frozen=True` stops the clock at the moment of creation, so only advance() moves it."""

    def __init__(self, user: str = "dev", background: bool = False, table: FakeTable | None = None,
                 frozen: bool = False):
        self.table = table or FakeTable()
        self.user = user
        self.background = background
        self.base = int(time.time()) if frozen else None
        self.offset = 0  # seconds added to the clock; move it with advance()
        self._tick = 0   # a frozen clock still hands out rising milliseconds, so stamps keep their order
        self.params: dict[str, str | None] = {"session-key": "local-session-key",
                                               "allowed-github-login": user}
        backend = self

        class _Lambda:
            def invoke(self, FunctionName, InvocationType, Payload):
                event = json.loads(Payload)
                if backend.background:
                    threading.Thread(target=backend.judge.lambda_handler, args=(event, None), daemon=True).start()
                else:
                    backend.judge.lambda_handler(event, None)
                return {"StatusCode": 202}

        stub = types.ModuleType("boto3")
        stub.resource = lambda _service, **_kw: types.SimpleNamespace(Table=lambda _name: self.table)
        stub.client = lambda service, **_kw: _Lambda() if service == "lambda" else types.SimpleNamespace()
        os.environ.setdefault("TABLE", "mogi-local")
        os.environ.setdefault("JUDGE_FN", "mogi-judge-local")
        judge_dir = str(ROOT / "backend" / "judge")
        if judge_dir not in sys.path:
            sys.path.insert(0, judge_dir)
        real = sys.modules.get("boto3")
        sys.modules["boto3"] = stub
        try:
            self.api = _load("mogi_api_handler", ROOT / "backend" / "api" / "handler.py")
            self.judge = _load("mogi_judge_handler", ROOT / "backend" / "judge" / "handler.py")
        finally:
            if real is not None:
                sys.modules["boto3"] = real
            else:
                del sys.modules["boto3"]
        # SSM parameters come from self.params. A missing required one fails as it does in the Lambda.
        def param(name: str, required: bool = True):
            val = self.params.get(name)
            if required and not val:
                raise self.api.ApiError(500, f"SSM parameter /mogi/{name} is not set")
            return val
        self.api._param = param
        self.api._now = self.now
        self.api._now_ms = self.now_ms
        self.judge._now = self.now

    # ------------------------------------------------------------ clock
    def now(self) -> int:
        return (self.base if self.base is not None else int(time.time())) + self.offset

    def now_ms(self) -> int:
        if self.base is None:
            return int(time.time() * 1000) + self.offset * 1000
        self._tick = (self._tick + 1) % 1000
        return (self.base + self.offset) * 1000 + self._tick

    def advance(self, days: float = 0, seconds: int = 0) -> None:
        self.offset += int(days * 86400) + seconds

    # ------------------------------------------------------------ data
    def seed(self, items: list[dict]) -> None:
        """Write problems the way tools/ingest.py uploads them: one META row and one PROBLIST row."""
        sys.path.insert(0, str(ROOT / "tools"))
        from ingest import problist_row
        for it in items:
            self.table.put_item(Item={"pk": f"PROB#{it['pid']}", "sk": "META", **it})
            self.table.put_item(Item=problist_row(it))

    def progress(self, pid: str) -> dict:
        return self.table.get_item(Key={"pk": f"USER#{self.user}", "sk": f"PROG#{pid}"}).get("Item", {})

    # ------------------------------------------------------------ requests
    def token(self, days: int = 365) -> str:
        return self.api.jwt_encode({"u": self.user, "cli": True, "exp": time.time() + days * 86400})

    def event(self, method: str, path: str, body: dict | None = None, headers: dict | None = None,
              query: dict | None = None) -> dict:
        """An API Gateway HTTP API (payload v2) event, as the Lambda receives it."""
        hdrs = {"authorization": f"Bearer {self.token()}", "x-mogi": "1"}
        hdrs.update({k.lower(): v for k, v in (headers or {}).items()})
        return {"rawPath": path, "requestContext": {"http": {"method": method}},
                "headers": {k: v for k, v in hdrs.items() if v is not None},
                "queryStringParameters": query or None,
                "body": json.dumps(body) if body is not None else None, "isBase64Encoded": False}

    def call(self, method: str, path: str, body: dict | None = None, headers: dict | None = None,
             query: dict | None = None) -> tuple[int, dict]:
        """(status, parsed JSON body) for one request, signed in as self.user."""
        resp = self.api.lambda_handler(self.event(method, "/api" + path, body, headers, query), None)
        return resp["statusCode"], json.loads(resp.get("body") or "{}")
