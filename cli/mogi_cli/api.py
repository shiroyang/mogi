"""Thin HTTP client for the mogi API (stdlib urllib)."""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Callable

from . import __version__


class ApiError(Exception):
    def __init__(self, status: int, msg: str):
        super().__init__(msg)
        self.status, self.msg = status, msg


def pid_path(pid: str) -> str:
    return "/".join(urllib.parse.quote(seg, safe="") for seg in pid.split("/"))


class Api:
    def __init__(self, site: str, token: str | None = None, timeout: int = 30):
        self.site = site.rstrip("/")
        self.token = token
        self.timeout = timeout

    # ------------------------------------------------------------ transport
    def _call(self, method: str, path: str, body: dict | None = None) -> dict:
        headers = {"Accept": "application/json", "x-mogi": "1",
                   "User-Agent": f"mogi-cli/{__version__}"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(f"{self.site}/api{path}", data=data,
                                     method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return json.loads(resp.read().decode() or "{}")
        except urllib.error.HTTPError as e:
            try:
                payload = json.loads(e.read().decode() or "{}")
            except ValueError:
                payload = {}
            msg = payload.get("error") or f"HTTP {e.code}"
            if e.code == 401:
                msg = "not signed in — run `mogi login`"
            raise ApiError(e.code, msg) from None
        except urllib.error.URLError as e:
            raise ApiError(0, f"cannot reach {self.site}: {e.reason}") from None

    # ------------------------------------------------------------ endpoints
    def me(self) -> dict:
        return self._call("GET", "/me")

    def problems(self) -> dict:
        return self._call("GET", "/problems")

    def problem(self, pid: str) -> dict:
        return self._call("GET", f"/problems/{pid_path(pid)}")

    def set_meta(self, pid: str, **fields) -> dict:
        return self._call("PUT", f"/problems/{pid_path(pid)}/meta", fields)

    def submit(self, pid: str, code: str, mode: str) -> dict:
        return self._call("POST", "/submit", {"pid": pid, "code": code, "mode": mode})

    def poll(self, pid: str, sk: str) -> dict:
        return self._call("GET", f"/submissions/{pid_path(pid)}/{urllib.parse.quote(sk, safe='')}")

    def activity(self) -> dict:
        return self._call("GET", "/activity")

    def judge(self, pid: str, code: str, mode: str,
              on_tick: Callable[[int], None] | None = None, timeout_s: float = 125) -> dict:
        """Submit and poll until a verdict lands (the judge usually answers in ~1 s)."""
        sub = self.submit(pid, code, mode)
        deadline = time.time() + timeout_s
        i = 0
        while time.time() < deadline:
            time.sleep(0.7 if i < 6 else 1.5)
            res = self.poll(pid, sub["sk"])
            if res.get("verdict") != "PENDING":
                return res
            i += 1
            if on_tick:
                on_tick(i)
        raise ApiError(0, "timed out waiting for a verdict — check the submissions list on the web")
