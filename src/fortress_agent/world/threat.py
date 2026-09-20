from __future__ import annotations

from dataclasses import dataclass

from fortress_agent.domain.state import GameState, Position


@dataclass(frozen=True, slots=True)
class ThreatSnapshot:
    base_risk: float
    max_cell_threat: float
    enemy_count: int
    nearest_enemy_eta: int | None


class ThreatMap:
    def __init__(
        self,
        *,
        width: int = 41,
        height: int = 32,
    ) -> None:
        self.width = width
        self.height = height
        self._values = [0.0] * (width * height)

    def add(self, x: int, y: int, value: float) -> None:
        if not (0 <= x < self.width and 0 <= y < self.height):
            return
        self._values[y * self.width + x] += max(0.0, value)

    def value(self, x: int, y: int) -> float:
        if not (0 <= x < self.width and 0 <= y < self.height):
            return float("inf")
        return self._values[y * self.width + x]

    def max_value(self) -> float:
        return max(self._values, default=0.0)

    def as_extra_cost(
        self,
        *,
        scale: float = 1.0,
    ) -> dict[tuple[int, int], float]:
        result = {}

        for y in range(self.height):
            for x in range(self.width):
                value = self.value(x, y)
                if value > 0:
                    result[(x, y)] = value * scale

        return result


class ThreatMapBuilder:
    """Deterministic first-order threat model.

    It intentionally uses only observable fields:
    enemy attack, hp, position and own-base positions.
    The propagation model can later be replaced without changing feature or
    pathfinding interfaces.
    """

    def __init__(
        self,
        *,
        width: int = 41,
        height: int = 32,
        propagation_radius: int = 6,
    ) -> None:
        self.width = width
        self.height = height
        self.propagation_radius = propagation_radius

    def build(
        self,
        state: GameState,
    ) -> tuple[ThreatMap, ThreatSnapshot]:
        threat = ThreatMap(
            width=self.width,
            height=self.height,
        )

        bases = self._own_base_positions(state)
        nearest_eta: int | None = None
        base_risk = 0.0

        for enemy in state.enemies:
            attack = float(enemy.attack or 1)
            hp_factor = max(1.0, float(enemy.hp) / 40.0)
            source_threat = attack * hp_factor

            for dy in range(
                -self.propagation_radius,
                self.propagation_radius + 1,
            ):
                for dx in range(
                    -self.propagation_radius,
                    self.propagation_radius + 1,
                ):
                    distance = max(abs(dx), abs(dy))

                    if distance > self.propagation_radius:
                        continue

                    value = source_threat / (distance + 1.0)
                    threat.add(
                        enemy.position.x + dx,
                        enemy.position.y + dy,
                        value,
                    )

            for base in bases:
                eta = (
                    abs(enemy.position.x - base.x)
                    + abs(enemy.position.y - base.y)
                )

                if nearest_eta is None or eta < nearest_eta:
                    nearest_eta = eta

                base_risk += source_threat / (eta + 1.0)

        # Normalize to a stable [0, 1) style risk feature.
        normalized_base_risk = (
            base_risk / (base_risk + 50.0)
            if base_risk > 0
            else 0.0
        )

        snapshot = ThreatSnapshot(
            base_risk=normalized_base_risk,
            max_cell_threat=threat.max_value(),
            enemy_count=len(state.enemies),
            nearest_enemy_eta=nearest_eta,
        )

        return threat, snapshot

    @staticmethod
    def _own_base_positions(
        state: GameState,
    ) -> tuple[Position, ...]:
        bases = []

        for building in state.buildings:
            if "base" not in building.building_type.lower():
                continue

            if (
                building.owner is not None
                and building.owner.lower()
                in {"enemy", "opponent"}
            ):
                continue

            bases.append(building.position)

        return tuple(bases)
