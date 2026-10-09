"""Split a corpus solution file into (reference, harness, imports, required API, stub).

The corpus contract (真题/*/solutions/*.py): every file is a standalone stdlib-only
script whose tests live entirely inside ``if __name__ == "__main__":`` and print
``N/N checks passed`` on success. That means the module body above the guard is the
reference implementation, and the guard block is a ready-made test harness that can
be appended verbatim to *someone else's* implementation of the same names.
"""
from __future__ import annotations

import ast
import builtins
from dataclasses import dataclass, field


@dataclass
class Split:
    reference: str          # module body without the __main__ guard
    harness: str            # the __main__ guard block, verbatim
    imports: str            # module-level import statements (harness may rely on them)
    required: list[str]     # top-level names the harness uses -> the API to implement
    stub: str               # starter code: signatures of the required API
    checks: int = 0         # filled by the ingester after a verification run
    warnings: list[str] = field(default_factory=list)


def _is_main_guard(node: ast.stmt) -> bool:
    if not isinstance(node, ast.If):
        return False
    t = node.test
    return (
        isinstance(t, ast.Compare)
        and isinstance(t.left, ast.Name) and t.left.id == "__name__"
        and len(t.ops) == 1 and isinstance(t.ops[0], ast.Eq)
        and len(t.comparators) == 1
        and isinstance(t.comparators[0], ast.Constant)
        and t.comparators[0].value == "__main__"
    )


def _top_level_names(tree: ast.Module, skip: ast.stmt) -> set[str]:
    names: set[str] = set()
    for node in tree.body:
        if node is skip:
            continue
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            for tgt in node.targets:
                for n in ast.walk(tgt):
                    if isinstance(n, ast.Name):
                        names.add(n.id)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                names.add((alias.asname or alias.name).split(".")[0])
    return names


def _harness_local_names(guard: ast.If) -> set[str]:
    local: set[str] = set()
    for n in ast.walk(guard):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            local.add(n.name)
        elif isinstance(n, ast.Name) and isinstance(n.ctx, (ast.Store, ast.Del)):
            local.add(n.id)
        elif isinstance(n, (ast.Import, ast.ImportFrom)):
            for alias in n.names:
                local.add((alias.asname or alias.name).split(".")[0])
    return local


def _func_stub(node: ast.FunctionDef | ast.AsyncFunctionDef, indent: str = "") -> str:
    prefix = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
    sig = f"{indent}{prefix} {node.name}({ast.unparse(node.args)})"
    if node.returns is not None:
        sig += f" -> {ast.unparse(node.returns)}"
    lines = [f"{d}" for d in (f"{indent}@{ast.unparse(dec)}" for dec in node.decorator_list)]
    lines.append(sig + ":")
    doc = ast.get_docstring(node)
    if doc:
        first = doc.strip().splitlines()[0]
        lines.append(f'{indent}    """{first}"""')
    lines.append(f"{indent}    ...")
    return "\n".join(lines)


def _method_stub(node: ast.FunctionDef) -> str:
    """A reference top-level function re-emitted as a Solution method."""
    args = ast.unparse(node.args)
    sig = f"    def {node.name}(self{', ' + args if args else ''})"
    if node.returns is not None:
        sig += f" -> {ast.unparse(node.returns)}"
    lines = [sig + ":"]
    doc = ast.get_docstring(node)
    if doc:
        first = doc.strip().splitlines()[0]
        lines.append(f'        """{first}"""')
    lines.append("        ...")
    return "\n".join(lines)


def _class_stub(node: ast.ClassDef) -> str:
    bases = ", ".join(ast.unparse(b) for b in node.bases)
    lines = [f"class {node.name}({bases}):" if bases else f"class {node.name}:"]
    doc = ast.get_docstring(node)
    if doc:
        lines.append(f'    """{doc.strip().splitlines()[0]}"""')
    methods = [n for n in node.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    for m in methods:
        lines.append(_func_stub(m, indent="    "))
        lines.append("")
    if not methods:
        lines.append("    ...")
    return "\n".join(lines).rstrip()


def split_solution(source: str) -> Split:
    tree = ast.parse(source)
    guards = [n for n in tree.body if _is_main_guard(n)]
    if not guards:
        raise ValueError("no `if __name__ == '__main__':` guard found")
    guard = guards[-1]
    warnings = [] if len(guards) == 1 else [f"{len(guards)} __main__ guards; using the last"]

    lines = source.splitlines(keepends=True)
    start, end = guard.lineno - 1, guard.end_lineno
    harness = "".join(lines[start:end])
    reference = ("".join(lines[:start]) + "".join(lines[end:])).rstrip() + "\n"

    import_nodes = [n for n in tree.body if isinstance(n, (ast.Import, ast.ImportFrom))]
    imports = "\n".join(ast.get_source_segment(source, n) or "" for n in import_nodes)

    top = _top_level_names(tree, skip=guard)
    local = _harness_local_names(guard)
    used = {
        n.id for n in ast.walk(guard)
        if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)
    }
    builtin_names = set(dir(builtins))
    import_names = {
        (alias.asname or alias.name).split(".")[0]
        for n in import_nodes for alias in n.names
    }
    required = sorted(used & top - local - builtin_names - import_names)

    by_name: dict[str, ast.stmt] = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            by_name[node.name] = node
        elif isinstance(node, ast.Assign):
            for tgt in node.targets:
                if isinstance(tgt, ast.Name):
                    by_name[tgt.id] = node
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            by_name[node.target.id] = node

    # A few corpus files define their test plumbing (check()/checks counter/
    # raises()/fixture builders) at module level instead of inside the guard.
    # That plumbing is harness, not exercise: relocate everything top-level from
    # the first plumbing definition down to the guard into the harness, and drop
    # it from the required API so the stub never asks the user to implement it.
    plumb_roots = [n for n in required
                   if n.lstrip("_").startswith(("check", "expect", "assert", "raise"))]
    root_nodes = [by_name[n] for n in plumb_roots if n in by_name]
    if root_nodes:
        boundary = min(n.lineno for n in root_nodes)
        moved_src, moved_names, cut = [], set(), [(start, end)]
        for node in tree.body:
            if node is guard or node.lineno < boundary:
                continue
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                                 ast.ClassDef, ast.Assign, ast.AnnAssign)):
                first = min([node.lineno] +
                            [d.lineno for d in getattr(node, "decorator_list", [])])
                moved_src.append("".join(lines[first - 1:node.end_lineno]))
                cut.append((first - 1, node.end_lineno))
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    moved_names.add(node.name)
                else:
                    for tgt in ast.walk(node):
                        if isinstance(tgt, ast.Name) and isinstance(tgt.ctx, ast.Store):
                            moved_names.add(tgt.id)
        if moved_src:
            harness = ("# -- test plumbing (relocated from module level) --\n"
                       + "\n".join(moved_src) + "\n\n" + harness)
            # and out of the reference, so the model answer shown after AC (and
            # the reference docs) is the solution alone, not the test scaffolding
            reference = "".join(ln for i, ln in enumerate(lines)
                                if not any(a <= i < b for a, b in cut)).rstrip() + "\n"
            required = [r for r in required if r not in moved_names]
            warnings.append(f"relocated test plumbing into harness: {sorted(moved_names)}")

    # Stub style. If every required name is a plain function, emit a
    # LeetCode-style `class Solution` with those functions as methods — the
    # judge adapts it back to top-level names at run time. Problems whose API
    # includes classes or constants get those directly (LeetCode does the same
    # for design questions: you implement the named class).
    nodes = [by_name.get(n) for n in required]
    leetcode_style = bool(required) and all(
        isinstance(n, ast.FunctionDef) and not n.decorator_list for n in nodes
    )
    stubs: list[str] = []
    if leetcode_style:
        stubs.append("# Implement inside class Solution — LeetCode style."
                     "\n# (Plain top-level functions with the same names also work.)")
        stubs.append("class Solution:")
        for node in nodes:
            stubs.append(_method_stub(node))
            stubs.append("")
    else:
        stubs.append("# The tests instantiate/call these names directly — implement them as given.")
        stubs.append("")
        for name, node in zip(required, nodes):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                stubs.append(_func_stub(node))
            elif isinstance(node, ast.ClassDef):
                stubs.append(_class_stub(node))
            else:
                stubs.append(f"{name} = ...  # define this (see the tests for the expected shape)")
            stubs.append("")
    stub = "\n".join(stubs).rstrip() + ("\n" if stubs else "")

    return Split(reference=reference, harness=harness, imports=imports,
                 required=required, stub=stub, warnings=warnings)


def strip_main_guard(source: str) -> str:
    """Neutralize the user's own __main__ block so their scratch tests don't
    collide with the appended harness. Each removed line is replaced by a
    comment so line numbers stay identical to what the user sees in the editor
    (tracebacks are mapped back to editor lines). Returns the source unchanged
    if it doesn't parse — the judge reports the SyntaxError as CE."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return source
    guards = [n for n in tree.body if _is_main_guard(n)]
    if not guards:
        return source
    lines = source.splitlines(keepends=True)
    for guard in guards:
        for i in range(guard.lineno - 1, guard.end_lineno):
            lines[i] = "# [your __main__ block is not judged]\n"
    return "".join(lines)
