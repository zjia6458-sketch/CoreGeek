from __future__ import annotations

from fortress_agent.domain.policy_state import PolicyState
from fortress_agent.domain.state import GameState
from fortress_agent.memory.world import WorldMemoryView
from fortress_agent.world.threat import ThreatMapBuilder

from .base import FeatureExtractor


class ThreatFeatureExtractor(FeatureExtractor):
    feature_id = "threat"

    def __init__(
        self,
        builder: ThreatMapBuilder | None = None,
    ) -> None:
        self._builder = builder or ThreatMapBuilder()

    def extract(
        self,
        state: GameState,
        memory: WorldMemoryView,
        policy_state: PolicyState,
    ):
        _, snapshot = self._builder.build(state)

        return {
            "combat.base_risk": snapshot.base_risk,
            "combat.enemy_count": snapshot.enemy_count,
            "combat.max_cell_threat": snapshot.max_cell_threat,
            "combat.nearest_enemy_eta": snapshot.nearest_enemy_eta,
        }
