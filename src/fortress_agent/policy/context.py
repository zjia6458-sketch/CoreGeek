from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Mapping

from fortress_agent.domain.policy_state import PolicyState
from fortress_agent.domain.state import GameState
from fortress_agent.memory.strategic import StrategicMemoryView
from fortress_agent.memory.feedback import RuntimeFeedbackMemoryView
from fortress_agent.memory.world import WorldMemoryView
from fortress_agent.memory.economy import MiningRuntimeMemoryView
from fortress_agent.memory.robot_trajectory import RobotTrajectoryMemoryView
from fortress_agent.safety.deadline import DeadlineView


@dataclass(frozen=True, slots=True)
class PolicyContext:
    state: GameState
    world_memory: WorldMemoryView
    policy_state: PolicyState
    deadline: DeadlineView
    features: Mapping[str, object] = field(
        default_factory=lambda: MappingProxyType({})
    )
    strategic_memory: StrategicMemoryView | None = None
    feedback_memory: RuntimeFeedbackMemoryView | None = None
    correlation_id: str | None = None
    mining_memory: MiningRuntimeMemoryView | None = None
    robot_trajectory: RobotTrajectoryMemoryView | None = None
