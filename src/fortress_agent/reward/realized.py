from __future__ import annotations

from dataclasses import dataclass

from fortress_agent.domain.reward import RewardBreakdown
from fortress_agent.domain.state import GameState


@dataclass(frozen=True, slots=True)
class MemoryRewardDelta:
    newly_discovered_cells: int = 0
    newly_discovered_resources: int = 0


class RealizedRewardCalculator:
    """Calculate observed reward after the environment responds.

    The official scoreboard delta is kept separate from shaping signals.
    This later becomes the basis for Experience/Outcome.
    """

    def calculate(
        self,
        previous: GameState,
        current: GameState,
        *,
        memory_delta: MemoryRewardDelta | None = None,
    ) -> RewardBreakdown:
        memory_delta = memory_delta or MemoryRewardDelta()

        score = float(current.score_self - previous.score_self)

        previous_inventory = self._inventory_market_value(previous)
        current_inventory = self._inventory_market_value(current)
        economy = current_inventory - previous_inventory

        information = (
            memory_delta.newly_discovered_cells * 1.0
            + memory_delta.newly_discovered_resources * 2.0
        )

        # Survival shaping: loss of own base HP is negative.
        previous_base_hp = self._own_base_hp(previous)
        current_base_hp = self._own_base_hp(current)
        survival = float(current_base_hp - previous_base_hp)

        total = score + economy + information + survival

        return RewardBreakdown(
            score=score,
            survival=survival,
            economy=economy,
            information=information,
            total=total,
        )

    @staticmethod
    def _inventory_market_value(state: GameState) -> float:
        value = 0.0

        for actor in state.characters:
            for item in actor.inventory:
                unit = state.market_prices.get(item.item_type, 1.0)
                value += item.amount * unit

        return value

    @staticmethod
    def _own_base_hp(state: GameState) -> int:
        total = 0

        for building in state.buildings:
            building_type = building.building_type.lower()
            if (
                "base" not in building_type
                and building_type != "station"
            ):
                continue
            if building.owner is not None and building.owner.lower() in {
                "opponent",
                "enemy",
            }:
                continue
            if building.hp is not None:
                total += building.hp

        return total
