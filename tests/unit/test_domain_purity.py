"""Structural guards on the trusted domain core.

These tests read the domain's own source. They exist because three of the
project's load-bearing claims are claims about what the code *cannot* do:

- money never touches binary floating point,
- time is only ever read from an injected clock,
- authorization is reachable without a model, a framework or the harness.

A behavioural test can show that today's code obeys those rules. Only a
structural test keeps tomorrow's code from quietly breaking them.
"""

import ast
from collections.abc import Callable
from pathlib import Path

import maf_lab.domain

DOMAIN_ROOT = Path(maf_lab.domain.__file__).parent

FORBIDDEN_TIME_ATTRIBUTES = frozenset({"utcnow", "today", "fromtimestamp"})
FORBIDDEN_TIME_MODULE_CALLS = frozenset(
    {"time", "monotonic", "monotonic_ns", "time_ns", "perf_counter", "process_time"}
)
FORBIDDEN_MODULES = frozenset(
    {
        "time",
        "random",
        "secrets",
        "uuid",
        "os",
        "pathlib",
        "socket",
        "sqlite3",
        "requests",
        "httpx",
        "openai",
        "agent_framework",
    }
)
FORBIDDEN_BUILTINS = frozenset({"open", "eval", "exec", "compile", "__import__"})


def domain_modules() -> list[Path]:
    return sorted(DOMAIN_ROOT.rglob("*.py"))


def parsed_modules() -> list[tuple[Path, ast.Module]]:
    return [(path, ast.parse(path.read_text(encoding="utf-8"))) for path in domain_modules()]


def source_location(path: Path, node: ast.AST) -> str:
    return f"{path.relative_to(DOMAIN_ROOT)}:{getattr(node, 'lineno', 0)}"


def offences(forbidden: Callable[[ast.AST], bool]) -> list[str]:
    """Locations of every node in the domain that `forbidden` rejects."""
    return [
        source_location(path, node)
        for path, tree in parsed_modules()
        for node in ast.walk(tree)
        if forbidden(node)
    ]


def imported_modules(node: ast.AST) -> list[str]:
    if isinstance(node, ast.Import):
        return [alias.name for alias in node.names]
    if isinstance(node, ast.ImportFrom):
        return [node.module or ""]
    return []


def imports_matching(forbidden: Callable[[str], bool]) -> list[str]:
    return [
        f"{source_location(path, node)} imports {name}"
        for path, tree in parsed_modules()
        for node in ast.walk(tree)
        for name in imported_modules(node)
        if forbidden(name)
    ]


def is_float_literal(node: ast.AST) -> bool:
    return isinstance(node, ast.Constant) and isinstance(node.value, float)


def is_float_conversion(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "float"
    )


def is_float_annotation(node: ast.AST) -> bool:
    if isinstance(node, ast.AnnAssign | ast.arg):
        annotations = [node.annotation]
    elif isinstance(node, ast.FunctionDef):
        annotations = [node.returns]
    else:
        return False
    return any(
        isinstance(inner, ast.Name) and inner.id == "float"
        for annotation in annotations
        if annotation is not None
        for inner in ast.walk(annotation)
    )


def is_true_division(node: ast.AST) -> bool:
    return isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div)


def reads_the_system_clock(node: ast.AST) -> bool:
    if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
        return False
    attribute = node.func.attr
    base = node.func.value
    base_name = base.id if isinstance(base, ast.Name) else getattr(base, "attr", "")
    return (
        attribute in FORBIDDEN_TIME_ATTRIBUTES
        or (attribute == "now" and base_name in {"datetime", "date"})
        or (base_name == "time" and attribute in FORBIDDEN_TIME_MODULE_CALLS)
    )


def is_dynamic_execution(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id in FORBIDDEN_BUILTINS
    )


def test_there_is_a_domain_to_guard() -> None:
    """Fails loudly if the glob stops finding modules, so no guard passes vacuously."""
    names = {path.name for path in domain_modules()}
    assert {"money.py", "clock.py", "canonical.py"} <= names
    assert {"models.py", "policy.py", "state.py", "tools.py"} <= names


def test_no_floating_point_literals() -> None:
    assert offences(is_float_literal) == []


def test_no_float_conversions() -> None:
    assert offences(is_float_conversion) == []


def test_no_float_annotations() -> None:
    assert offences(is_float_annotation) == []


def test_no_true_division() -> None:
    """True division produces a float, so balance arithmetic uses `//` or nothing."""
    assert offences(is_true_division) == []


def test_no_system_clock_reads() -> None:
    assert offences(reads_the_system_clock) == []


def test_no_dynamic_execution_or_file_access() -> None:
    assert offences(is_dynamic_execution) == []


def test_no_nondeterministic_or_io_imports() -> None:
    assert imports_matching(lambda name: name.split(".")[0] in FORBIDDEN_MODULES) == []


def test_the_domain_imports_nothing_else_from_the_project() -> None:
    """Authorization must be reachable without the runner, evaluators or exporters."""
    assert (
        imports_matching(
            lambda name: name.startswith("maf_lab.")
            and not name.startswith("maf_lab.domain")
        )
        == []
    )
