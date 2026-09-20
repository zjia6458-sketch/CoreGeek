from __future__ import annotations

from abc import ABC, abstractmethod
from types import MappingProxyType
from typing import Mapping

from fortress_agent.domain.policy_state import PolicyState
from fortress_agent.domain.state import GameState
from fortress_agent.memory.world import WorldMemoryView


class FeatureExtractor(ABC):
    """PolicyContext 特征提取器抽象类。

    主要实现：``features/basic.py::BasicWorldFeatureExtractor`` 与
    ``features/threat.py::ThreatFeatureExtractor``。所有实现通过 FeatureRegistry
    聚合，特征 key 不允许冲突。
    """

    feature_id: str

    @abstractmethod
    def extract(
        self,
        state: GameState,
        memory: WorldMemoryView,
        policy_state: PolicyState,
    ) -> Mapping[str, object]:
        ...


class FeatureRegistry:
    def __init__(self) -> None:
        self._extractors: list[FeatureExtractor] = []
        self._ids: set[str] = set()

    def register(self, extractor: FeatureExtractor) -> None:
        if extractor.feature_id in self._ids:
            raise ValueError(
                f"duplicate feature extractor: {extractor.feature_id}"
            )
        self._extractors.append(extractor)
        self._ids.add(extractor.feature_id)

    def build(
        self,
        state: GameState,
        memory: WorldMemoryView,
        policy_state: PolicyState,
    ) -> Mapping[str, object]:
        result: dict[str, object] = {}

        for extractor in self._extractors:
            values = dict(
                extractor.extract(
                    state,
                    memory,
                    policy_state,
                )
            )

            overlap = set(result).intersection(values)
            if overlap:
                raise ValueError(
                    f"feature key collision from {extractor.feature_id}: "
                    f"{sorted(overlap)}"
                )

            result.update(values)

        return MappingProxyType(result)
