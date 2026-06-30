"""One-shot helper: add type annotations across the test suite.

Deterministic, formatting-preserving (libcst) pass that:
  * adds `-> None` to test functions and value-less helpers,
  * gives pytest fixtures a return annotation (`Iterator[V]`/`V`/`None`),
  * annotates parameters from a fixture->type table + pytest builtins,
    falling back to `Any` when a type can't be inferred cheaply,
  * inserts any imports the new annotations need.

Run with: uv run --with libcst python scripts/annotate_tests.py
This script is idempotent: it never overwrites an existing annotation.
"""

from __future__ import annotations

import ast
import os

import libcst as cst

SRC = "src"
TESTS = "tests"

# --- external/stdlib types we are willing to name precisely -----------------
# token -> import statement needed to use it
KNOWN_IMPORTS: dict[str, str] = {
    "Any": "from typing import Any",
    "Iterator": "from collections.abc import Iterator",
    "Path": "from pathlib import Path",
    "Mock": "from unittest.mock import Mock",
    "MagicMock": "from unittest.mock import MagicMock",
    "FastAPI": "from fastapi import FastAPI",
    "TestClient": "from fastapi.testclient import TestClient",
    "pytest": "import pytest",
}

PYTEST_BUILTINS: dict[str, str] = {
    "tmp_path": "Path",
    "monkeypatch": "pytest.MonkeyPatch",
    "capsys": "pytest.CaptureFixture[str]",
    "capfd": "pytest.CaptureFixture[str]",
    "caplog": "pytest.LogCaptureFixture",
    "request": "pytest.FixtureRequest",
    "recwarn": "pytest.WarningsRecorder",
    "tmp_path_factory": "pytest.TempPathFactory",
}

MOCK_FUNCS = {"Mock", "MagicMock", "NonCallableMock", "AsyncMock", "create_autospec"}


def build_class_module_map() -> dict[str, str]:
    out: dict[str, str] = {}
    for dp, _, fns in os.walk(SRC):
        if "__pycache__" in dp:
            continue
        for fn in fns:
            if not fn.endswith(".py"):
                continue
            p = os.path.join(dp, fn)
            mod = p[len(SRC) + 1 : -3].replace("/", ".")
            try:
                tree = ast.parse(open(p).read())
            except SyntaxError:
                continue
            for n in tree.body:
                if isinstance(n, ast.ClassDef):
                    out.setdefault(n.name, mod)
    return out


CLASS_MOD = build_class_module_map()


def call_name(call: ast.Call) -> str | None:
    f = call.func
    if isinstance(f, ast.Name):
        return f.id
    if isinstance(f, ast.Attribute):
        return f.attr
    return None


def infer_value_type(node: ast.FunctionDef | ast.AsyncFunctionDef) -> tuple[str, bool]:
    """Return (value_type, yields) for a fixture/helper body.

    value_type is what a consumer receives; yields says whether the function
    yields (so its own return annotation should be Iterator[value_type]).
    """
    yields = False
    expr: ast.expr | None = None
    assigns: dict[str, ast.expr] = {}
    for n in ast.walk(node):
        if (
            isinstance(n, ast.Assign)
            and len(n.targets) == 1
            and isinstance(n.targets[0], ast.Name)
        ):
            assigns[n.targets[0].id] = n.value
    for n in ast.walk(node):
        if isinstance(n, ast.Yield):
            yields = True
            if n.value is not None and expr is None:
                expr = n.value
        if isinstance(n, ast.Return) and n.value is not None and expr is None:
            expr = n.value
    if expr is None:
        return "None", yields
    # resolve a bare name to its last assignment
    if isinstance(expr, ast.Name) and expr.id in assigns:
        expr = assigns[expr.id]
    t = _expr_type(expr)
    return t, yields


def _expr_type(expr: ast.expr) -> str:
    if isinstance(expr, ast.Dict):
        return "dict[str, Any]"
    if isinstance(expr, (ast.List, ast.ListComp)):
        return "list[Any]"
    if isinstance(expr, ast.Constant):
        return type(expr.value).__name__ if expr.value is not None else "None"
    if isinstance(expr, ast.Call):
        name = call_name(expr)
        if name in MOCK_FUNCS:
            return "MagicMock"
        if name in CLASS_MOD:
            return name
        if name in ("FastAPI", "TestClient"):
            return name
    return "Any"


def is_fixture(node: cst.FunctionDef) -> bool:
    for d in node.decorators:
        dump = cst.Module([]).code_for_node(d.decorator)
        if "fixture" in dump:
            return True
    return False


# Build fixture value-type table from all test files first.
def build_fixture_table() -> dict[str, str]:
    table: dict[str, str] = {}
    for dp, _, fns in os.walk(TESTS):
        if "__pycache__" in dp:
            continue
        for fn in fns:
            if not fn.endswith(".py"):
                continue
            tree = ast.parse(open(os.path.join(dp, fn)).read())
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if any("fixture" in ast.dump(d) for d in node.decorator_list):
                        if node.returns is not None:
                            ann = ast.unparse(node.returns)
                            # unwrap Iterator[X]/Generator[X, ...]
                            inner = ann
                            for w in (
                                "Iterator[",
                                "Generator[",
                                "Iterable[",
                                "AsyncIterator[",
                            ):
                                if ann.startswith(w):
                                    inner = ann[len(w) : -1].split(",")[0].strip()
                                    break
                            table[node.name] = inner
                            continue
                        v, _ = infer_value_type(node)
                        if node.name.startswith("mock") and v == "Any":
                            v = "MagicMock"
                        table[node.name] = v
    return table


FIXTURE_TYPE = build_fixture_table()


def param_type(name: str) -> str:
    if name in PYTEST_BUILTINS:
        return PYTEST_BUILTINS[name]
    if name in FIXTURE_TYPE and FIXTURE_TYPE[name] != "None":
        return FIXTURE_TYPE[name]
    return "Any"


def tokens_of(type_str: str) -> set[str]:
    """Top-level identifiers a type string references, for import tracking."""
    toks: set[str] = set()
    try:
        for n in ast.walk(ast.parse(type_str, mode="eval")):
            if isinstance(n, ast.Name):
                toks.add(n.id)
            if isinstance(n, ast.Attribute):
                base = n
                while isinstance(base, ast.Attribute):
                    base = base.value
                if isinstance(base, ast.Name):
                    toks.add(base.id)
    except SyntaxError:
        pass
    return toks


class Annotator(cst.CSTTransformer):
    def __init__(self) -> None:
        self.needed: set[str] = set()
        self.class_stack: list[str] = []

    def visit_ClassDef(self, node: cst.ClassDef) -> None:
        self.class_stack.append(node.name.value)

    def leave_ClassDef(self, o: cst.ClassDef, u: cst.ClassDef) -> cst.ClassDef:
        self.class_stack.pop()
        return u

    def _note(self, type_str: str) -> str:
        for tok in tokens_of(type_str):
            if tok in KNOWN_IMPORTS or tok in CLASS_MOD:
                self.needed.add(tok)
        return type_str

    def leave_FunctionDef(
        self, node: cst.FunctionDef, updated: cst.FunctionDef
    ) -> cst.FunctionDef:
        name = node.name.value
        fixture = is_fixture(node)
        in_test_class = any(c.startswith("Test") for c in self.class_stack)
        is_test = name.startswith("test_") or (
            in_test_class and name.startswith("test")
        )

        # --- parameters ---
        params = updated.params
        new_params = []
        for p in params.params:
            pname = p.name.value
            if pname in ("self", "cls") or p.annotation is not None:
                new_params.append(p)
                continue
            t = param_type(pname)
            new_params.append(
                p.with_changes(
                    annotation=cst.Annotation(cst.parse_expression(self._note(t)))
                )
            )

        def ann_star(p: cst.Param | cst.MaybeSentinel | None):
            if (
                isinstance(p, cst.Param)
                and p.annotation is None
                and p.name.value not in ("self", "cls")
            ):
                return p.with_changes(
                    annotation=cst.Annotation(cst.parse_expression(self._note("Any")))
                )
            return p

        star_arg = (
            ann_star(params.star_arg)
            if isinstance(params.star_arg, cst.Param)
            else params.star_arg
        )
        star_kwarg = ann_star(params.star_kwarg)
        kwonly = [ann_star(p) for p in params.kwonly_params]
        posonly = []
        for p in params.posonly_params:
            if p.annotation is None and p.name.value not in ("self", "cls"):
                posonly.append(
                    p.with_changes(
                        annotation=cst.Annotation(
                            cst.parse_expression(self._note(param_type(p.name.value)))
                        )
                    )
                )
            else:
                posonly.append(p)

        updated = updated.with_changes(
            params=params.with_changes(
                params=new_params,
                star_arg=star_arg,
                star_kwarg=star_kwarg,
                kwonly_params=kwonly,
                posonly_params=posonly,
            )
        )

        # --- return type ---
        if updated.returns is None:
            if is_test:
                rt = "None"
            elif fixture:
                v, yields = infer_value_type(_to_ast(node))
                if node.name.value.startswith("mock") and v == "Any":
                    v = "MagicMock"
                # honour an existing table entry (may be more precise)
                v = FIXTURE_TYPE.get(name, v)
                rt = f"Iterator[{v}]" if yields else v
            else:
                v, yields = infer_value_type(_to_ast(node))
                rt = f"Iterator[{v}]" if yields and v != "None" else v
            updated = updated.with_changes(
                returns=cst.Annotation(cst.parse_expression(self._note(rt)))
            )
        return updated


def _to_ast(node: cst.FunctionDef) -> ast.FunctionDef:
    code = cst.Module([]).code_for_node(node)
    return ast.parse(code).body[0]  # type: ignore[return-value]


def existing_top_names(tree: ast.Module) -> set[str]:
    names: set[str] = set()
    for n in tree.body:
        if isinstance(n, ast.Import):
            for a in n.names:
                names.add((a.asname or a.name).split(".")[0])
        if isinstance(n, ast.ImportFrom):
            for a in n.names:
                names.add(a.asname or a.name)
    return names


def import_for(tok: str) -> str:
    if tok in KNOWN_IMPORTS:
        return KNOWN_IMPORTS[tok]
    return f"from {CLASS_MOD[tok]} import {tok}"


def insert_imports(code: str, needed: set[str]) -> str:
    tree = ast.parse(code)
    have = existing_top_names(tree)
    # 'pytest' token only needs a plain import pytest
    missing = []
    for tok in sorted(needed):
        base = tok.split(".")[0]
        if base in have:
            continue
        missing.append(import_for(base))
    if not missing:
        return code
    missing = sorted(set(missing))
    lines = code.splitlines(keepends=True)
    # find insertion point: after module docstring + __future__ + existing imports
    insert_at = 0
    seen_code = False
    for i, n in enumerate(tree.body):
        if isinstance(n, (ast.Import, ast.ImportFrom)):
            insert_at = n.end_lineno or insert_at
            seen_code = True
        elif isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant) and i == 0:
            insert_at = n.end_lineno or insert_at
        else:
            if seen_code:
                break
    block = "".join(line + "\n" for line in missing)
    return "".join(lines[:insert_at]) + block + "".join(lines[insert_at:])


def main() -> None:
    changed = 0
    for dp, _, fns in os.walk(TESTS):
        if "__pycache__" in dp:
            continue
        for fn in fns:
            if not fn.endswith(".py"):
                continue
            p = os.path.join(dp, fn)
            src = open(p).read()
            module = cst.parse_module(src)
            ann = Annotator()
            new = module.visit(ann)
            out = new.code
            if ann.needed:
                out = insert_imports(out, ann.needed)
            if out != src:
                open(p, "w").write(out)
                changed += 1
    print(f"annotated {changed} files")


if __name__ == "__main__":
    main()
