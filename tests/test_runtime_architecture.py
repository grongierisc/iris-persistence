from __future__ import annotations

import ast
from pathlib import Path

PACKAGE_ROOT = Path(__file__).parents[1] / "iris_persistence"
MODE_BOUNDARY = {"runtime.py", "_runtime_backend.py"}
WRAPPER_BACKEND = "_runtime_backend.py"


def test_backend_details_are_confined_to_runtime_boundary():
    violations: list[str] = []
    for path in PACKAGE_ROOT.rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))

        for node in ast.walk(tree):
            outside_wrapper = path.name != WRAPPER_BACKEND
            if outside_wrapper and isinstance(node, ast.Import) and any(
                alias.name == "iris" for alias in node.names
            ):
                violations.append(f"{path}: imports iris")
            if outside_wrapper and isinstance(node, ast.ImportFrom) and node.module == "iris":
                violations.append(f"{path}: imports from iris")
            if (
                outside_wrapper
                and isinstance(node, ast.Attribute)
                and node.attr in {"_oref", "_db"}
            ):
                violations.append(f"{path}:{node.lineno}: accesses {node.attr}")
            if (
                path.name not in MODE_BOUNDARY
                and isinstance(node, ast.Constant)
                and node.value in {"embedded", "native"}
            ):
                violations.append(f"{path}:{node.lineno}: branches on backend mode")

    assert violations == []
