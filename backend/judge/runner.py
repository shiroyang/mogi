"""Execute a submission against a problem's harness and produce a verdict.

The submitted code and the harness are concatenated into one script and run in a
subprocess with a scrubbed environment (no AWS credentials reach user code), an
isolated interpreter (-I), rlimits, and a wall-clock timeout. Verdicts:

    AC  accepted — exit 0 and the corpus contract line "N/N checks passed"
    WA  wrong answer — an AssertionError from the harness
    RE  runtime error — any other exception, or tests that never completed
    TLE time limit exceeded
    CE  compile error — the submission itself doesn't parse
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
OUTPUT_CAP = 16_000  # chars kept from each stream; DDB items must stay small

SAFE_ENV = {
    "PATH": "/usr/local/bin:/usr/bin:/bin",
    "HOME": "/tmp",
    "LANG": "C.UTF-8",
    "PYTHONIOENCODING": "utf-8",
}


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


def judge(user_code: str, harness: str, imports: str, *,
          time_limit_s: int = 20, mem_mb: int = 640,
          python: str = sys.executable) -> dict:
    # CE first, on the submission alone, for a clean message.
    try:
        compile(user_code, "solution.py", "exec")
    except SyntaxError as e:
        return {"verdict": "CE", "passed": 0, "total": None, "ms": 0,
                "detail": f"SyntaxError: {e.msg} (line {e.lineno})",
                "stdout": "", "stderr": ""}

    # __future__ imports are only legal at the very top of a file (before even a
    # demoted docstring), and both the submission and the corpus imports use
    # `from __future__ import annotations`. Hoist every future-import out of both
    # blocks and re-emit them as the script's first lines.
    future_re = re.compile(r"^\s*from __future__ import\s+(.+?)\s*$")
    features: set[str] = set()

    def defuture(text: str) -> str:
        kept = []
        for ln in text.splitlines():
            m = future_re.match(ln)
            if m:
                features.update(f.strip() for f in m.group(1).split(","))
            else:
                kept.append(ln)
        return "\n".join(kept)

    body = defuture(strip_main_guard(user_code))
    imports_clean = defuture(imports)
    features.add("annotations")
    header = "".join(f"from __future__ import {f}\n" for f in sorted(features))
    script = (
        header + body
        + "\n\n# ==== appended by mogi: the problem's own tests ====\n"
        + imports_clean + "\n\n" + harness
    )

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
            return {"verdict": "TLE", "passed": len(PASS_RE.findall(out)), "total": None,
                    "ms": ms, "detail": f"no verdict within {time_limit_s}s",
                    "stdout": _tail(out), "stderr": ""}
        ms = int((time.monotonic() - t0) * 1000)

    stdout, stderr = proc.stdout or "", proc.stderr or ""
    passed = len(PASS_RE.findall(stdout))
    count = COUNT_RE.search(stdout)

    if proc.returncode == 0 and count:
        n = int(count.group(2))
        return {"verdict": "AC", "passed": int(count.group(1)), "total": n, "ms": ms,
                "detail": f"{count.group(1)}/{n} checks passed",
                "stdout": _tail(stdout), "stderr": ""}

    if "AssertionError" in stderr:
        msg = ""
        m = re.search(r"AssertionError:? ?(.*)$", stderr.strip(), re.M)
        if m and m.group(1).strip():
            msg = m.group(1).strip()
        else:  # bare assert — show the failing source line from the traceback
            src = re.findall(r'File "[^"]*solution\.py", line \d+.*\n\s*(.+)', stderr)
            msg = src[-1].strip() if src else "assertion failed"
        return {"verdict": "WA", "passed": passed, "total": None, "ms": ms,
                "detail": msg, "stdout": _tail(stdout), "stderr": _tail(stderr)}

    if proc.returncode != 0 or not count:
        m = re.search(r"^(\w+Error|\w+Exception|KeyboardInterrupt|MemoryError)\b.*$",
                      stderr.strip(), re.M)
        detail = (m.group(0) if m
                  else stderr.strip().splitlines()[-1] if stderr.strip()
                  else "tests did not complete (no verdict line printed)")
        return {"verdict": "RE", "passed": passed, "total": None, "ms": ms,
                "detail": detail[:400], "stdout": _tail(stdout), "stderr": _tail(stderr)}

    return {"verdict": "RE", "passed": passed, "total": None, "ms": ms,
            "detail": "unclassified result", "stdout": _tail(stdout), "stderr": _tail(stderr)}
