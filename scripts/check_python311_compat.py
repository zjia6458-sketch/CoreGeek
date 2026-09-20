#!/usr/bin/env python3
from __future__ import annotations

import ast
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"


def is_dataclass(node: ast.ClassDef) -> bool:
    for decorator in node.decorator_list:
        if isinstance(decorator, ast.Name) and decorator.id == "dataclass":
            return True
        if (
            isinstance(decorator, ast.Call)
            and isinstance(decorator.func, ast.Name)
            and decorator.func.id == "dataclass"
        ):
            return True
    return False


def main() -> int:
    violations: list[str] = []
    paths = [ROOT / "main3.py", *SRC.rglob("*.py")]

    for path in paths:
        source = path.read_text(encoding="utf-8")
        try:
            tree = ast.parse(
                source,
                filename=str(path),
                feature_version=(3, 11),
            )
        except SyntaxError as exc:
            violations.append(
                f"Python 3.11 grammar: {path.relative_to(ROOT)}:{exc.lineno}: {exc.msg}"
            )
            continue

        for node in tree.body:
            if not isinstance(node, ast.ClassDef) or not is_dataclass(node):
                continue

            for stmt in node.body:
                if not isinstance(stmt, ast.AnnAssign) or stmt.value is None:
                    continue

                value = stmt.value
                name = (
                    stmt.target.id
                    if isinstance(stmt.target, ast.Name)
                    else ast.unparse(stmt.target)
                )

                if isinstance(value, (ast.Dict, ast.List, ast.Set)):
                    violations.append(
                        f"mutable dataclass default: {path.relative_to(ROOT)}:{stmt.lineno} "
                        f"{node.name}.{name}; use field(default_factory=...)"
                    )
                    continue

                if isinstance(value, ast.Call) and isinstance(value.func, ast.Name):
                    if value.func.id in {"dict", "list", "set", "MappingProxyType"}:
                        violations.append(
                            f"container dataclass default: {path.relative_to(ROOT)}:{stmt.lineno} "
                            f"{node.name}.{name}={ast.unparse(value)}; "
                            "use field(default_factory=...)"
                        )

    if violations:
        print("Python 3.11 compatibility check FAILED", file=sys.stderr)
        for item in violations:
            print(f"- {item}", file=sys.stderr)
        return 1

    print("Python 3.11 compatibility check PASSED")
    print(f"checked {len(paths)} production Python files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
