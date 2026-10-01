from __future__ import annotations

import ast
from pathlib import Path


def test_all_audit_record_calls_supply_remote_keyword() -> None:
    project_root = Path(__file__).resolve().parents[1]
    missing: list[str] = []

    for source_path in (project_root / "cms").rglob("*.py"):
        tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if not (
                isinstance(func, ast.Attribute)
                and func.attr == "record"
                and isinstance(func.value, ast.Name)
                and func.value.id == "audit"
            ):
                continue
            if not any(keyword.arg == "remote" for keyword in node.keywords):
                relative = source_path.relative_to(project_root)
                missing.append(f"{relative}:{node.lineno}")

    assert not missing, "AuditLog.record() without remote=: " + ", ".join(missing)
