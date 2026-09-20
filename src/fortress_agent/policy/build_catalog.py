from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

from fortress_agent.game_rules.catalog import building_rule


@dataclass(frozen=True, slots=True)
class BuildRecipe:
    building_name: str
    required_items: Mapping[str, int]
    strategic_value: float
    gold_cost: int = 0
    max_count: int | None = None
    enabled: bool = True


class BuildCatalog:
    """Authoritative build costs from the supplied official game rules.

    An optional mapping may override values for local fixtures, but production
    no longer starts with an empty catalog.
    """

    OFFICIAL = {
        "wall": {"required_items": {"stone": 1}, "gold_cost": 0, "strategic_value": 5.0, "max_count": 20},
        "gatling": {"required_items": {}, "gold_cost": 25, "strategic_value": 8.0, "max_count": 3},
        "railgun": {"required_items": {}, "gold_cost": 25, "strategic_value": 8.5, "max_count": 3},
        "rocket": {"required_items": {}, "gold_cost": 25, "strategic_value": 9.0, "max_count": 3},
    }

    def __init__(self, recipes: tuple[BuildRecipe, ...] = ()) -> None:
        self._recipes = MappingProxyType({
            recipe.building_name.lower(): recipe
            for recipe in recipes
            if recipe.enabled
        })

    @classmethod
    def official_default(cls) -> "BuildCatalog":
        return cls.from_mapping(cls.OFFICIAL, use_official_when_empty=False)

    @classmethod
    def from_mapping(
        cls,
        config: Mapping[str, Mapping[str, object]] | None,
        *,
        use_official_when_empty: bool = True,
    ):
        source = config
        if use_official_when_empty and not source:
            source = cls.OFFICIAL
        recipes = []
        for name, raw in (source or {}).items():
            required = raw.get("required_items", {})
            official = building_rule(str(name))
            recipes.append(BuildRecipe(
                building_name=str(name).lower(),
                required_items=MappingProxyType({str(k).lower(): int(v) for k, v in dict(required).items()}),
                strategic_value=float(raw.get("strategic_value", 4.0)),
                gold_cost=int(raw.get("gold_cost", official.build_gold_cost if official else 0)),
                max_count=(int(raw["max_count"]) if raw.get("max_count") is not None else (official.max_count if official else None)),
                enabled=bool(raw.get("enabled", True)),
            ))
        return cls(tuple(recipes))

    def recipes(self) -> tuple[BuildRecipe, ...]:
        return tuple(self._recipes[key] for key in sorted(self._recipes))

    def get(self, building_name: str) -> BuildRecipe | None:
        return self._recipes.get(building_name.lower())

    @property
    def configured(self) -> bool:
        return bool(self._recipes)
