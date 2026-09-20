from __future__ import annotations

from abc import ABC, abstractmethod

from fortress_agent.domain.action import Action
from fortress_agent.policy.context import PolicyContext
from fortress_agent.policy.strategy import StrategyProfile


class CandidateGenerator(ABC):
    """候选动作生成器抽象基类。

    典型实现位置：
    - ``candidates/basic.py``：移动、探索、采集、攻击、资源接近；
    - ``candidates/navigation.py``：任务点、Vendor、WeaponShop、基地返回；
    - ``candidates/business.py``：买卖、建造、任务、宝藏、使用物品。

    新动作类型通常先新增一个该接口实现，再在
    ``application/basic_policy.py::build_basic_policy_runtime`` 中注册。
    """

    generator_id: str
    tags: frozenset[str]

    @abstractmethod
    def generate(
        self,
        ctx: PolicyContext,
        strategy: StrategyProfile,
    ) -> tuple[Action, ...]:
        ...


class CandidateRegistry:
    def __init__(self) -> None:
        self._generators: list[CandidateGenerator] = []
        self._ids: set[str] = set()

    def register(self, generator: CandidateGenerator) -> None:
        if generator.generator_id in self._ids:
            raise ValueError(
                f"duplicate candidate generator: {generator.generator_id}"
            )
        self._generators.append(generator)
        self._ids.add(generator.generator_id)

    def generate_all(
        self,
        ctx: PolicyContext,
        strategy: StrategyProfile,
    ) -> tuple[Action, ...]:
        actions: list[Action] = []

        for generator in self._generators:
            if not generator.tags.intersection(strategy.candidate_tags):
                continue

            # Candidate 阶段包含 A* 等相对昂贵的计算。预算不足时停止继续
            # 扩展候选面，交由上层 Deadline fallback 返回安全空响应。
            if ctx.deadline.remaining() <= 0.55:
                break

            actions.extend(generator.generate(ctx, strategy))

        # Stable de-duplication.
        return tuple(dict.fromkeys(actions))
