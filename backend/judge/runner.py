"""Execute a submission against a problem's harness and produce a verdict.

The submitted code and the harness are concatenated into one script and run in a
subprocess with a scrubbed environment (no AWS credentials reach user code), an
isolated interpreter (-I), rlimits, and a wall-clock timeout. Verdicts:

    AC  accepted — exit 0 and the corpus contract line "N/N checks passed"
    WA  wrong answer — an AssertionError from the harness
    RE  runtime error — any other exception, or tests that never completed
    TLE time limit exceeded
    CE  compile error — the submission itself doesn't parse

Every internal rewrite of the user's code is line-count-preserving, so a frame
reported as "your code line N" is line N in the user's editor. A LeetCode-style
`class Solution` submission is adapted back to the top-level names the harness
calls, unless the user already defined them at module level.
"""
from __future__ import annotations

import re
import resource
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from splitter import strip_main_guard

COUNT_RE = re.compile(r"(\d+)/(\d+) checks passed")
PASS_RE = re.compile(r"^PASS\b", re.M)
FRAME_RE = re.compile(r'File "[^"]*solution\.py", line (\d+)(?:, in (\S+))?')
OUTPUT_CAP = 16_000  # chars kept from each stream; DDB items must stay small

SAFE_ENV = {
    "PATH": "/usr/local/bin:/usr/bin:/bin",
    "HOME": "/tmp",
    "LANG": "C.UTF-8",
    "PYTHONIOENCODING": "utf-8",
}

ADAPTER = """\
# ==== mogi adapter: accept LeetCode-style `class Solution` submissions ====
try:
    _mogi_solution = Solution()  # noqa: F821
except NameError:
    _mogi_solution = None
if _mogi_solution is not None:
    for _mogi_name in {names!r}:
        if _mogi_name not in globals() and hasattr(_mogi_solution, _mogi_name):
            globals()[_mogi_name] = getattr(_mogi_solution, _mogi_name)
"""


def _limits(mem_bytes: int, cpu_seconds: int):
    """Best-effort rlimits: enforced on Lambda's Linux; macOS rejects some
    (notably RLIMIT_AS), which is fine for local runs — the wall-clock timeout
    still applies everywhere."""
    def apply():
        for lim, val in ((resource.RLIMIT_AS, (mem_bytes, mem_bytes)),
                         (resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds + 2)),
                         (resource.RLIMIT_FSIZE, (8_000_000, 8_000_000))):
            try:
                resource.setrlimit(lim, val)
            except (ValueError, OSError):
                pass
    return apply


def _tail(text: str, cap: int = OUTPUT_CAP) -> str:
    return text if len(text) <= cap else "…" + text[-cap:]


def _defuture(text: str, features: set[str]) -> str:
    """Collect and comment out `from __future__ import …` lines in place —
    same line count, so editor line numbers survive."""
    out = []
    for ln in text.splitlines(keepends=True):
        m = re.match(r"^\s*from __future__ import\s+(.+?)\s*$", ln)
        if m:
            features.update(f.strip() for f in m.group(1).split(","))
            out.append("# [hoisted] " + ln.lstrip())
        else:
            out.append(ln)
    return "".join(out)


def _nl(text: str) -> str:
    return text if text.endswith("\n") or not text else text + "\n"


def _assemble(user_code: str, harness: str, imports: str,
              required: list[str]) -> tuple[str, list[tuple[int, int, str]]]:
    features: set[str] = set()
    body = _defuture(strip_main_guard(user_code), features)
    imports_clean = _defuture(imports, features)
    features.add("annotations")

    header = "".join(f"from __future__ import {f}\n" for f in sorted(features))
    adapter = ADAPTER.format(names=sorted(required)) if required else ""
    tests = ("# ==== appended by mogi: the problem's own tests ====\n"
             + _nl(imports_clean) + "\n" + adapter + "\n" + _nl(harness))

    script, sections, line = "", [], 1
    for label, text in (("setup", header), ("your code", _nl(body)), ("tests", tests)):
        n = text.count("\n")
        sections.append((line, line + n - 1, label))
        script += text
        line += n
    return script, sections


def _annotate(stderr: str, sections: list[tuple[int, int, str]],
              script: str) -> list[str]:
    """Rewrite traceback frames as 'your code line N' / 'tests line N' with the
    offending source line attached."""
    def locate(n: int) -> tuple[str, int]:
        for a, b, label in sections:
            if a <= n <= b:
                return label, n - a + 1
        return "script", n

    lines = script.splitlines()
    frames = []
    for m in FRAME_RE.finditer(stderr):
        n = int(m.group(1))
        label, local = locate(n)
        src = lines[n - 1].strip() if 0 < n <= len(lines) else ""
        where = m.group(2) or "<module>"
        frames.append(f"{label} line {local}, in {where}:  {src}")
    return frames


def judge(user_code: str, harness: str, imports: str, *,
          required: list[str] | None = None,
          time_limit_s: int = 20, mem_mb: int = 640,
          python: str = sys.executable) -> dict:
    def result(verdict: str, passed: int, total, ms: int, detail: str,
               stdout: str = "", stderr: str = "", trace: str = "") -> dict:
        return {"verdict": verdict, "passed": passed, "total": total, "ms": ms,
                "detail": detail[:600], "stdout": _tail(stdout),
                "stderr": _tail(stderr), "trace": trace[:2400]}

    # CE first, on the submission alone — line numbers match the editor.
    try:
        compile(user_code, "solution.py", "exec")
    except SyntaxError as e:
        caret = f"    {(e.text or '').rstrip()}" if e.text else ""
        return result("CE", 0, None, 0,
                      f"SyntaxError: {e.msg} — your code line {e.lineno}",
                      trace=caret and f"your code line {e.lineno}:  {caret.strip()}")

    script, sections = _assemble(user_code, harness, imports, required or [])

    with tempfile.TemporaryDirectory(prefix="mogi_") as tmp:
        path = Path(tmp) / "solution.py"
        path.write_text(script, encoding="utf-8")
        t0 = time.monotonic()
        try:
            proc = subprocess.run(
                [python, "-I", str(path)],
                capture_output=True, text=True, timeout=time_limit_s,
                cwd=tmp, env=SAFE_ENV,
                preexec_fn=_limits(mem_mb * 1024 * 1024, time_limit_s),
            )
        except subprocess.TimeoutExpired as e:
            ms = int((time.monotonic() - t0) * 1000)
            out = e.stdout or b""
            out = out.decode("utf-8", "replace") if isinstance(out, bytes) else out
            passed = len(PASS_RE.findall(out))
            last = PASS_RE.findall(out) and out.strip().splitlines()[-1] or ""
            return result("TLE", passed, None, ms,
                          f"no verdict within {time_limit_s}s"
                          + (f" — last completed: {last}" if last else ""),
                          stdout=out)
        ms = int((time.monotonic() - t0) * 1000)

    stdout, stderr = proc.stdout or "", proc.stderr or ""
    passed = len(PASS_RE.findall(stdout))
    count = COUNT_RE.search(stdout)
    frames = _annotate(stderr, sections, script)
    trace = "\n".join(frames[-8:])
    loc = f" — {frames[-1]}" if frames else ""

    if proc.returncode == 0 and count:
        n = int(count.group(2))
        return result("AC", int(count.group(1)), n, ms,
                      f"{count.group(1)}/{n} checks passed", stdout=stdout)

    if "AssertionError" in stderr:
        m = re.search(r"AssertionError:? ?(.*)$", stderr.strip(), re.M)
        msg = (m.group(1).strip() if m and m.group(1).strip()
               else "assertion failed")
        return result("WA", passed, None, ms, msg + loc,
                      stdout=stdout, stderr=stderr, trace=trace)

    m = re.search(r"^(\w+(?:Error|Exception|Interrupt|Exit)):?.*$", stderr.strip(), re.M)
    detail = (m.group(0) if m
              else stderr.strip().splitlines()[-1] if stderr.strip()
              else "tests did not complete (no verdict line printed)")
    return result("RE", passed, None, ms, detail + loc,
                  stdout=stdout, stderr=stderr, trace=trace)
