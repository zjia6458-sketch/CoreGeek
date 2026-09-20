from __future__ import annotations

from fortress_agent.domain.policy_state import PolicyState
from fortress_agent.domain.state import GameState
from fortress_agent.memory.world import WorldMemoryView

from .base import FeatureExtractor


class BasicWorldFeatureExtractor(FeatureExtractor):
    feature_id = "basic_world"

    def extract(
        self,
        state: GameState,
        memory: WorldMemoryView,
        policy_state: PolicyState,
    ):
        return {
            "time.phase": state.phase,
            "time.turns_until_phase_change": (
                state.turns_until_phase_change
            ),
            "score.gap": state.score_self - state.score_opponent,
            "memory.available_resource_count": len(
                memory.available_resources()
            ),
            "memory.frontier_count": len(
                memory.frontier_cells()
            ),
        }
