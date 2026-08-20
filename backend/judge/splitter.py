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

    stubs: list[str] = []
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
    for name in required:
        node = by_name.get(name)
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
    """Remove the user's own __main__ block so their scratch tests don't collide
    with the appended harness. Returns the source unchanged if it doesn't parse
    (the judge will report the SyntaxError as CE)."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return source
    guards = [n for n in tree.body if _is_main_guard(n)]
    if not guards:
        return source
    lines = source.splitlines(keepends=True)
    for guard in sorted(guards, key=lambda g: -g.lineno):
        del lines[guard.lineno - 1:guard.end_lineno]
    return "".join(lines)
