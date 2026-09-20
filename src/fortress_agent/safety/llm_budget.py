from __future__ import annotations

from dataclasses import dataclass

from fortress_agent.domain.state import GameState


@dataclass(frozen=True, slots=True)
class LLMBudgetView:
    day: int
    used_normal_calls: int
    limit: int
    quota_error_seen: bool

    @property
    def remaining(self) -> int:
        if self.quota_error_seen:
            return 0
        return max(0, self.limit - self.used_normal_calls)


class LLMBudgetTracker:
    """Track normal LLM calls under the official 3-calls-per-game-day rule.

    Calls while an active self-evolution task is running are exempt and do not
    increment the daily normal-call counter.
    """

    def __init__(self, *, daily_limit: int = 3) -> None:
        self._limit = daily_limit
        self._day: int | None = None
        self._used = 0
        self._quota_error_seen = False

    def observe_state(self, state: GameState) -> None:
        if self._day != state.day:
            self._day = state.day
            self._used = 0
            self._quota_error_seen = False

        if any(
            error.error_code == 5
            for error in state.server_errors
        ):
            self._quota_error_seen = True

    def can_call(
        self,
        state: GameState,
        *,
        task_exempt: bool | None = None,
    ) -> bool:
        self.observe_state(state)

        if task_exempt is None:
            task_exempt = bool(state.phase_task.strip())

        if task_exempt:
            return True

        return (
            not self._quota_error_seen
            and self._used < self._limit
        )

    def record_call(
        self,
        state: GameState,
        *,
        task_exempt: bool | None = None,
    ) -> None:
        self.observe_state(state)

        if task_exempt is None:
            task_exempt = bool(state.phase_task.strip())

        if not task_exempt:
            if not self.can_call(
                state,
                task_exempt=False,
            ):
                raise RuntimeError(
                    "normal daily LLM budget exhausted"
                )
            self._used += 1

    def view(self) -> LLMBudgetView:
        return LLMBudgetView(
            day=self._day or 0,
            used_normal_calls=self._used,
            limit=self._limit,
            quota_error_seen=self._quota_error_seen,
        )
