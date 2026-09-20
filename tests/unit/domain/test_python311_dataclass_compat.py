from __future__ import annotations

import ast
from pathlib import Path
from types import MappingProxyType

import pytest

from fortress_agent.domain.state import GameState


ROOT = Path(__file__).resolve().parents[3]
SRC = ROOT / "src"


def _is_dataclass_decorator(node: ast.expr) -> bool:
    if isinstance(node, ast.Name):
        return node.id == "dataclass"
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        return node.func.id == "dataclass"
    return False


def test_all_production_python_uses_python311_grammar():
    paths = [ROOT / "main3.py", *SRC.rglob("*.py")]

    for path in paths:
        source = path.read_text(encoding="utf-8")
        ast.parse(
            source,
            filename=str(path),
            feature_version=(3, 11),
        )


def test_dataclasses_do_not_use_direct_mappingproxy_defaults():
    violations: list[str] = []

    for path in SRC.rglob("*.py"):
        tree = ast.parse(
            path.read_text(encoding="utf-8"),
            filename=str(path),
            feature_version=(3, 11),
        )

        for node in tree.body:
            if not isinstance(node, ast.ClassDef):
                continue
            if not any(
                _is_dataclass_decorator(dec)
                for dec in node.decorator_list
            ):
                continue

            for stmt in node.body:
                if not isinstance(stmt, ast.AnnAssign):
                    continue
                value = stmt.value
                if not isinstance(value, ast.Call):
                    continue
                if not isinstance(value.func, ast.Name):
                    continue
                if value.func.id != "MappingProxyType":
                    continue

                name = (
                    stmt.target.id
                    if isinstance(stmt.target, ast.Name)
                    else ast.unparse(stmt.target)
                )
                violations.append(
                    f"{path.relative_to(ROOT)}:{stmt.lineno} "
                    f"{node.name}.{name}"
                )

    assert not violations, (
        "Python 3.11 dataclasses reject direct MappingProxyType defaults. "
        "Use field(default_factory=lambda: MappingProxyType({})):\n"
        + "\n".join(violations)
    )


def _minimal_game_state() -> GameState:
    return GameState(
        round_id=1,
        day=1,
        phase="day",
        phase_round=1,
        turns_until_phase_change=69,
        score_self=0.0,
        score_opponent=0.0,
        anomaly_count=0,
        characters=(),
        enemies=(),
        buildings=(),
        resources=(),
        tasks=(),
        observed_cells=(),
        news=(),
        rumors=(),
        market_prices=MappingProxyType({}),
    )


def test_game_state_mapping_defaults_are_factory_created_and_read_only():
    first = _minimal_game_state()
    second = _minimal_game_state()

    assert isinstance(first.weapon_shop, MappingProxyType)
    assert isinstance(
        first.last_round_role_action_results,
        MappingProxyType,
    )

    assert first.weapon_shop is not second.weapon_shop
    assert (
        first.last_round_role_action_results
        is not second.last_round_role_action_results
    )

    with pytest.raises(TypeError):
        first.weapon_shop["Medicine"] = 10  # type: ignore[index]

    with pytest.raises(TypeError):
        first.last_round_role_action_results["10010"] = True  # type: ignore[index]
