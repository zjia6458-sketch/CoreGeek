from __future__ import annotations

from dataclasses import dataclass

from fortress_agent.application.basic_policy import (
    BasicPolicyRuntime,
)
from fortress_agent.domain.policy_state import PolicyState
from fortress_agent.domain.state import GameState
from fortress_agent.memory.world import WorldMemoryView
from fortress_agent.safety.deadline import Deadline


@dataclass(frozen=True, slots=True)
class ShadowDecisionPair:
    current: object
    candidate: object


class ShadowPolicyRunner:
    """Run champion/challenger using the same PolicyRuntime.

    Candidate gets an independent deadline budget and never blocks the action
    already selected by the current policy.
    """

    def __init__(
        self,
        policy_runtime: BasicPolicyRuntime,
        *,
        shadow_timeout_seconds: float = 0.75,
    ) -> None:
        self._policy = policy_runtime
        self._shadow_timeout_seconds = shadow_timeout_seconds

    async def compare_decisions(
        self,
        *,
        state: GameState,
        memory: WorldMemoryView,
        current_policy: PolicyState,
        candidate_policy: PolicyState,
        current_deadline,
    ):
        current = await self._policy.decide(
            state=state,
            world_memory=memory,
            policy_state=current_policy,
            deadline=current_deadline,
        )

        shadow_deadline = Deadline(
            self._shadow_timeout_seconds
        )

        candidate = await self._policy.decide(
            state=state,
            world_memory=memory,
            policy_state=candidate_policy,
            deadline=shadow_deadline,
        )

        return ShadowDecisionPair(
            current=current,
            candidate=candidate,
        )
