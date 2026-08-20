from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COGS = ROOT / "bot" / "cogs"


def _has_listener(func: ast.AsyncFunctionDef) -> bool:
    for dec in func.decorator_list:
        if isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute) and dec.func.attr == "listener":
            return True
        if isinstance(dec, ast.Attribute) and dec.attr == "listener":
            return True
    return True if not func.name.startswith("on_") else False


def _is_cog(node: ast.ClassDef) -> bool:
    for base in node.bases:
        if isinstance(base, ast.Name) and base.id in {"Cog", "ModuleCog"}:
            return True
        if isinstance(base, ast.Attribute) and base.attr in {"Cog", "ModuleCog"}:
            return True
    return False


def test_cog_event_handlers_are_listeners() -> None:
    missing: list[str] = []
    for path in sorted(COGS.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in tree.body:
            if not isinstance(node, ast.ClassDef) or not _is_cog(node):
                continue
            for item in node.body:
                if isinstance(item, ast.AsyncFunctionDef) and item.name.startswith("on_"):
                    if not _has_listener(item):
                        missing.append(f"{path.name}::{node.name}.{item.name}")
    assert missing == []


def test_no_syntax_errors() -> None:
    errors = []
    for path in (ROOT / "bot").rglob("*.py"):
        try:
            ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError as exc:
            errors.append(f"{path}: {exc}")
    assert errors == []
