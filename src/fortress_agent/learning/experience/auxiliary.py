from __future__ import annotations

from dataclasses import dataclass

from fortress_agent.domain.auxiliary import AuxiliaryDecision


@dataclass(frozen=True, slots=True)
class AuxiliaryExperienceRecord:
    experience_id: str
    decision_id: str
    round_id: int
    strategy_id: str
    decision: AuxiliaryDecision
    correlation_id: str | None = None


@dataclass(frozen=True, slots=True)
class AuxiliaryOutcomeRecord:
    outcome_id: str
    decision_id: str
    start_round: int
    end_round: int
    result_text: str = ""
    llm_response: str = ""
    transport_success: bool | None = None
    correlation_id: str | None = None


class InMemoryAuxiliaryExperienceStore:
    """prompt/executeCmd 的独立 Experience 存储。

    它不和 RoleAction 的统计混算，因为 executeCmd 的成功语义与 MOVE/BUILD 完全
    不同；但仍保留同样的 decision -> outcome 链，便于回放和 TaskSkill 学习。
    """

    def __init__(self) -> None:
        self._records: list[AuxiliaryExperienceRecord] = []
        self._outcomes: dict[str, AuxiliaryOutcomeRecord] = {}

    def append(self, record: AuxiliaryExperienceRecord) -> None:
        self._records.append(record)

    def attach(self, outcome: AuxiliaryOutcomeRecord) -> None:
        self._outcomes[outcome.decision_id] = outcome

    def all(self) -> tuple[AuxiliaryExperienceRecord, ...]:
        return tuple(self._records)

    def outcome_for(self, decision_id: str) -> AuxiliaryOutcomeRecord | None:
        return self._outcomes.get(decision_id)
