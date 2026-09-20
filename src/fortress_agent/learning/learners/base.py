from __future__ import annotations

from abc import ABC, abstractmethod

from fortress_agent.domain.policy_state import (
    PolicyPatch,
    PolicyState,
)
from fortress_agent.learning.experience.record import (
    ExperienceRecord,
    OutcomeRecord,
)


class OnlineLearner(ABC):
    """在线 Learner 抽象类。

    设计约束：Learner 只能观察 Experience/Outcome 并提出 PolicyPatch，不能直接
    修改生产 PolicyState。主要实现：``learners/threshold.py`` 与
    ``learners/utility.py``；Candidate 的创建/提升/回滚由 PolicyRepository 控制。
    """

    learner_id: str

    @abstractmethod
    def observe(
        self,
        exp: ExperienceRecord,
        outcome: OutcomeRecord | None,
    ) -> None:
        ...

    @abstractmethod
    def propose(
        self,
        current: PolicyState,
    ) -> PolicyPatch | None:
        ...


class LearnerRegistry:
    def __init__(self) -> None:
        self._learners: dict[str, OnlineLearner] = {}

    def register(self, learner: OnlineLearner) -> None:
        if learner.learner_id in self._learners:
            raise ValueError(
                f"duplicate learner: {learner.learner_id}"
            )
        self._learners[learner.learner_id] = learner

    def all(self) -> tuple[OnlineLearner, ...]:
        return tuple(
            self._learners[key]
            for key in sorted(self._learners)
        )
