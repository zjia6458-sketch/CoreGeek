from __future__ import annotations

from dataclasses import dataclass

from fortress_agent.domain.action import Action
from fortress_agent.domain.reward import RewardBreakdown
from fortress_agent.domain.utility import UtilityBreakdown


@dataclass(frozen=True, slots=True)
class ExperienceRecord:
    experience_id: str
    decision_id: str

    round_id: int
    day: int
    phase: str

    policy_version: int
    strategy_id: str

    feature_schema_version: int
    feature_vector: tuple[tuple[str, float | int | str | None], ...]

    action: Action
    action_probability: float

    predicted_utility: UtilityBreakdown

    latency_ms: float
    deadline_remaining_ms: float

    outcome_id: str | None = None
    correlation_id: str | None = None


@dataclass(frozen=True, slots=True)
class OutcomeRecord:
    outcome_id: str

    start_round: int
    end_round: int

    reward: RewardBreakdown

    confidence: float = 1.0
    action_legal: bool | None = None
    server_error_codes: tuple[int, ...] = ()
    server_error_messages: tuple[str, ...] = ()
    command_error_signatures: tuple[str, ...] = ()
    terrain_rule_signatures: tuple[str, ...] = ()
    action_failure_signatures: tuple[str, ...] = ()
    summon_treasure_result: int | None = None
    execute_cmd_result: str = ""
    correlation_id: str | None = None


@dataclass(frozen=True, slots=True)
class CreditLink:
    outcome_id: str
    decision_id: str
    weight: float

    def __post_init__(self) -> None:
        if not (0.0 <= self.weight <= 1.0):
            raise ValueError("credit weight must be in [0, 1]")
