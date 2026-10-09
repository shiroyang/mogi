"""Terminal rendering: verdicts (LeetCode-style), tables, colours."""
from __future__ import annotations

import os
import sys
import unicodedata

VERDICT_NAMES = {"AC": "Accepted", "WA": "Wrong Answer", "RE": "Runtime Error",
                 "TLE": "Time Limit Exceeded", "CE": "Compile Error", "PENDING": "Judging…"}
_COLORS = {"green": "32", "red": "31", "yellow": "33", "magenta": "35", "blue": "34",
           "cyan": "36", "dim": "2", "bold": "1"}
VERDICT_COLORS = {"AC": "green", "WA": "red", "RE": "yellow", "TLE": "magenta", "CE": "red"}


def use_color(stream=None) -> bool:
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("FORCE_COLOR"):
        return True
    stream = stream or sys.stdout
    return hasattr(stream, "isatty") and stream.isatty()


def paint(text: str, *styles: str, enabled: bool = True) -> str:
    if not enabled or not styles:
        return text
    codes = ";".join(_COLORS[s] for s in styles)
    return f"\033[{codes}m{text}\033[0m"


def width(s: str) -> int:
    return sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in s)


def fit(s: str, n: int) -> str:
    """Truncate to n display columns (CJK-aware) and pad."""
    s = str(s)
    if width(s) <= n:
        return s + " " * (n - width(s))
    out, w = "", 0
    for c in s:
        cw = 2 if unicodedata.east_asian_width(c) in "WF" else 1
        if w + cw > n - 1:
            break
        out += c
        w += cw
    return out + "…" + " " * (n - w - 1)


def table(headers: list[str], rows: list[list[str]], widths: list[int], color: bool) -> str:
    lines = [paint("  ".join(fit(h, w) for h, w in zip(headers, widths)).rstrip(), "dim", enabled=color)]
    for r in rows:
        lines.append("  ".join(fit(c, w) for c, w in zip(r, widths)).rstrip())
    return "\n".join(lines)


def status_glyph(status: str, color: bool) -> str:
    if status == "solved":
        return paint("✓", "green", enabled=color)
    if status == "attempted":
        return paint("◐", "yellow", enabled=color)
    return paint("·", "dim", enabled=color)


def format_verdict(res: dict, p: dict, color: bool, show_passes: bool = False) -> str:
    v = res.get("verdict", "?")
    c = VERDICT_COLORS.get(v, "blue")
    lines = [paint(f"{p.get('id', '')} — {p.get('title', '')}", "bold", enabled=color)]
    meta = f"{res.get('ms', 0)} ms"
    if v == "AC":
        meta += f" · {res.get('passed')}/{res.get('total')} checks"
    elif res.get("passed") is not None and v != "CE":
        n = res.get("passed") or 0
        meta += f" · {n} check{'s' if n != 1 else ''} passed before failure"
    lines.append(f"{paint(VERDICT_NAMES.get(v, v), c, 'bold', enabled=color)} · {meta}")
    if v != "AC" and res.get("detail"):
        lines.append(paint(f"  {res['detail']}", "dim", enabled=color))

    cases = res.get("cases") or []
    for i, case in enumerate(cases, 1):
        if case.get("status") == "pass":
            if show_passes:
                lines.append(f"  {paint('✓', 'green', enabled=color)} Case {i}  {case.get('label', '')}")
            continue
        lines.append(f"  {paint('✕', 'red', enabled=color)} Case {i}  {case.get('label', '')}".rstrip())
        if case.get("call"):
            lines.append(f"      {paint('Input    :', 'dim', enabled=color)} {case['call']}")
        if case.get("got") not in (None, ""):
            lines.append(f"      {paint('Output   :', 'dim', enabled=color)} {paint(str(case['got']), 'red', enabled=color)}")
        if case.get("want") not in (None, ""):
            lines.append(f"      {paint('Expected :', 'dim', enabled=color)} {paint(str(case['want']), 'green', enabled=color)}")
    if res.get("trace"):
        lines.append(paint("  where it failed:", "dim", enabled=color))
        lines += [f"    {ln}" for ln in str(res["trace"]).splitlines()]
    if res.get("stdout_tail"):
        lines.append(paint("  your stdout:", "dim", enabled=color))
        lines += [f"    {ln}" for ln in str(res["stdout_tail"]).splitlines()[-20:]]
    sync = res.get("sync")
    if sync:
        if sync.get("state") == "done":
            lines.append(paint(f"  ↑ synced to GitHub: {sync.get('path', '')}", "green", enabled=color))
        elif sync.get("state") in ("error", "skipped"):
            lines.append(paint(f"  ⚠ GitHub sync {sync['state']}: {sync.get('why', '')}", "yellow", enabled=color))
    return "\n".join(lines)
