from __future__ import annotations

from abc import ABC, abstractmethod
from collections import deque

from .record import CreditLink, ExperienceRecord, OutcomeRecord
from .stats import ContextKey, RunningStats


class ExperienceStore(ABC):
    """Experience/Outcome 存储抽象类。

    主要实现：
    - ``InMemoryExperienceStore``：比赛进程内的真实状态；
    - ``CompositeExperienceStore``：面向未来 Hot/Aggregate/Cold 分层的兼容外壳；
    - ``JournaledExperienceStore``：在不改变内存状态的前提下额外写审计日志。
    """

    @abstractmethod
    def append(self, exp: ExperienceRecord) -> None:
        ...

    @abstractmethod
    def attach_outcome(
        self,
        outcome: OutcomeRecord,
        credits: tuple[CreditLink, ...],
    ) -> None:
        ...

    @abstractmethod
    def recent(
        self,
        n: int,
    ) -> tuple[ExperienceRecord, ...]:
        ...

    @abstractmethod
    def all(
        self,
    ) -> tuple[ExperienceRecord, ...]:
        ...

    @abstractmethod
    def outcome_for(
        self,
        decision_id: str,
    ) -> OutcomeRecord | None:
        ...

    @abstractmethod
    def aggregate(
        self,
        key: ContextKey,
    ) -> RunningStats:
        ...


    def close(self) -> None:
        pass


class InMemoryExperienceStore(ExperienceStore):
    def __init__(
        self,
        *,
        hot_capacity: int = 512,
    ) -> None:
        self._records: list[ExperienceRecord] = []
        self._by_decision: dict[str, ExperienceRecord] = {}
        self._outcomes: dict[str, OutcomeRecord] = {}
        self._decision_to_outcome: dict[str, str] = {}
        self._hot = deque(maxlen=hot_capacity)
        self._aggregates: dict[ContextKey, RunningStats] = {}

    def append(self, exp: ExperienceRecord) -> None:
        if exp.decision_id in self._by_decision:
            raise ValueError(
                f"duplicate decision id: {exp.decision_id}"
            )

        self._records.append(exp)
        self._by_decision[exp.decision_id] = exp
        self._hot.append(exp)

    def attach_outcome(
        self,
        outcome: OutcomeRecord,
        credits: tuple[CreditLink, ...],
    ) -> None:
        if outcome.outcome_id in self._outcomes:
            raise ValueError(
                f"duplicate outcome id: {outcome.outcome_id}"
            )

        self._outcomes[outcome.outcome_id] = outcome

        for credit in credits:
            if credit.decision_id not in self._by_decision:
                raise KeyError(
                    f"unknown decision id: {credit.decision_id}"
                )

            self._decision_to_outcome[
                credit.decision_id
            ] = outcome.outcome_id

            exp = self._by_decision[credit.decision_id]
            key = ContextKey(
                phase=exp.phase,
                strategy_id=exp.strategy_id,
                action_type=exp.action.action_type,
            )

            stats = self._aggregates.setdefault(
                key,
                RunningStats(),
            )

            stats.update(
                outcome.reward.total * credit.weight
            )

    def recent(
        self,
        n: int,
    ) -> tuple[ExperienceRecord, ...]:
        if n <= 0:
            return ()
        return tuple(list(self._hot)[-n:])

    def all(
        self,
    ) -> tuple[ExperienceRecord, ...]:
        return tuple(self._records)

    def outcome_for(
        self,
        decision_id: str,
    ) -> OutcomeRecord | None:
        outcome_id = self._decision_to_outcome.get(
            decision_id
        )
        if outcome_id is None:
            return None
        return self._outcomes[outcome_id]

    def aggregate(
        self,
        key: ContextKey,
    ) -> RunningStats:
        return self._aggregates.setdefault(
            key,
            RunningStats(),
        )


class CompositeExperienceStore(ExperienceStore):
    """First implementation currently delegates to the in-memory core.

    The interface intentionally matches the future:
    HotBuffer + AggregateStore + ColdStore design. Persistent storage can be
    inserted without changing Learner/Shadow interfaces.
    """

    def __init__(
        self,
        inner: ExperienceStore | None = None,
    ) -> None:
        self._inner = inner or InMemoryExperienceStore()

    def append(self, exp):
        self._inner.append(exp)

    def attach_outcome(self, outcome, credits):
        self._inner.attach_outcome(outcome, credits)

    def recent(self, n):
        return self._inner.recent(n)

    def all(self):
        return self._inner.all()

    def outcome_for(self, decision_id):
        return self._inner.outcome_for(decision_id)

    def aggregate(self, key):
        return self._inner.aggregate(key)

    def close(self) -> None:
        self._inner.close()


class JournaledExperienceStore(ExperienceStore):
    """Operational experience store with append-only JSONL audit journal."""

    def __init__(self, inner: ExperienceStore, writer) -> None:
        self._inner = inner
        self._writer = writer

    def append(self, exp: ExperienceRecord) -> None:
        self._inner.append(exp)
        self._writer.write({
            'record_type': 'experience',
            'experience': exp,
        })

    def attach_outcome(self, outcome, credits) -> None:
        self._inner.attach_outcome(outcome, credits)
        self._writer.write({
            'record_type': 'outcome',
            'outcome': outcome,
            'credits': credits,
        })

    def recent(self, n):
        return self._inner.recent(n)

    def all(self):
        return self._inner.all()

    def outcome_for(self, decision_id):
        return self._inner.outcome_for(decision_id)

    def aggregate(self, key):
        return self._inner.aggregate(key)

    def close(self) -> None:
        self._inner.close()
        self._writer.close()
