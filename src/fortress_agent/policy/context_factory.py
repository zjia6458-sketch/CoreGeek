from __future__ import annotations

from fortress_agent.domain.policy_state import PolicyState
from fortress_agent.domain.state import GameState
from fortress_agent.features.base import FeatureRegistry
from fortress_agent.memory.strategic import StrategicMemoryView
from fortress_agent.memory.feedback import RuntimeFeedbackMemoryView
from fortress_agent.memory.world import WorldMemoryView
from fortress_agent.memory.economy import MiningRuntimeMemoryView
from fortress_agent.memory.robot_trajectory import RobotTrajectoryMemoryView
from fortress_agent.safety.deadline import DeadlineView

from .context import PolicyContext


class PolicyContextFactory:
    def __init__(self, features: FeatureRegistry) -> None:
        self._features = features

    def build(
        self,
        *,
        state: GameState,
        world_memory: WorldMemoryView,
        policy_state: PolicyState,
        deadline: DeadlineView,
        strategic_memory: StrategicMemoryView | None = None,
        feedback_memory: RuntimeFeedbackMemoryView | None = None,
        correlation_id: str | None = None,
        mining_memory: MiningRuntimeMemoryView | None = None,
        robot_trajectory: RobotTrajectoryMemoryView | None = None,
    ) -> PolicyContext:
        return PolicyContext(
            state=state,
            world_memory=world_memory,
            policy_state=policy_state,
            deadline=deadline,
            features=self._features.build(
                state,
                world_memory,
                policy_state,
            ),
            strategic_memory=strategic_memory,
            feedback_memory=feedback_memory,
            correlation_id=correlation_id,
            mining_memory=mining_memory,
            robot_trajectory=robot_trajectory,
        )
