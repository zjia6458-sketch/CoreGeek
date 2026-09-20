from __future__ import annotations

from dataclasses import dataclass

from fortress_agent.application.basic_policy import BasicPolicyRuntime
from fortress_agent.domain.decision import Decision
from fortress_agent.domain.policy_state import PolicyState
from fortress_agent.domain.state import GameState
from fortress_agent.memory.world import WorldMemoryView
from fortress_agent.safety.deadline import Deadline


@dataclass(frozen=True, slots=True)
class ReplayCase:
    case_id: str
    state: GameState
    memory: WorldMemoryView
    policy_state: PolicyState
    expected_action_repr: str | None = None


@dataclass(frozen=True, slots=True)
class ReplayResult:
    case_id: str
    decision: Decision
    matched_expected: bool | None


class ReplayEngine:
    def __init__(
        self,
        policy: BasicPolicyRuntime,
        *,
        timeout_seconds: float = 2.0,
    ) -> None:
        self._policy = policy
        self._timeout_seconds = timeout_seconds

    async def run(
        self,
        case: ReplayCase,
    ) -> ReplayResult:
        decision = await self._policy.decide(
            state=case.state,
            world_memory=case.memory,
            policy_state=case.policy_state,
            deadline=Deadline(
                self._timeout_seconds
            ),
        )

        matched = None

        if case.expected_action_repr is not None:
            matched = (
                repr(decision.action)
                == case.expected_action_repr
            )

        return ReplayResult(
            case_id=case.case_id,
            decision=decision,
            matched_expected=matched,
        )
