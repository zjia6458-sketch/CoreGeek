from __future__ import annotations

from dataclasses import dataclass

from fortress_agent.domain.state import GameState
from fortress_agent.safety.llm_budget import (
    LLMBudgetTracker,
)

from .prompt import StrategicPromptBuilder


@dataclass(frozen=True, slots=True)
class PlannedLLMRequest:
    prompt: str
    lore_id: str
    source_round: int


class StrategicLLMCoordinator:
    """Conservatively spend scarce normal LLM calls on unresolved lore.

    The coordinator never calls an LLM itself. It only decides whether the
    outbound `prompt` field should be populated. This keeps network/protocol
    ownership in the judger interface.
    """

    def __init__(
        self,
        prompt_builder: StrategicPromptBuilder | None = None,
        *,
        max_attempts_per_lore: int = 1,
    ) -> None:
        self._builder = (
            prompt_builder
            or StrategicPromptBuilder()
        )
        self._max_attempts = (
            max_attempts_per_lore
        )
        self._attempts: dict[str, int] = {}

    def plan(
        self,
        *,
        state: GameState,
        memory,
        budget: LLMBudgetTracker,
        learned_hard_rules: tuple[str, ...] = (),
        safety_revision_key: str | None = None,
    ) -> PlannedLLMRequest | None:
        # Long-horizon strategic prompts are daytime-only. Active task prompts
        # are handled by the separate task-specific contract.
        if state.phase != "day":
            return None

        if state.phase_task.strip():
            return None

        if not budget.can_call(
            state,
            task_exempt=False,
        ):
            return None

        pending = memory.pending_lore()
        entry = None
        if pending:
            entry = sorted(
                pending,
                key=lambda item: (
                    item.first_seen_round,
                    item.lore_id,
                ),
                reverse=True,
            )[0]

        request_key: str | None = None
        if entry is not None:
            request_key = entry.lore_id
        elif safety_revision_key:
            # A newly learned authoritative execution-safety lesson deserves one
            # strategic re-analysis so the LLM advisory catches up with the
            # deterministic hard safety memory. The deterministic guard is
            # already active even if budget prevents this call.
            request_key = f"safety:{safety_revision_key}"

        if request_key is None:
            return None

        if (
            self._attempts.get(request_key, 0)
            >= self._max_attempts
        ):
            return None

        return PlannedLLMRequest(
            prompt=self._builder.build(
                state,
                learned_hard_rules=learned_hard_rules,
            ),
            lore_id=request_key,
            source_round=state.round_id,
        )

    def mark_sent(
        self,
        request: PlannedLLMRequest,
    ) -> None:
        self._attempts[
            request.lore_id
        ] = (
            self._attempts.get(
                request.lore_id,
                0,
            )
            + 1
        )
