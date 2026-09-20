from __future__ import annotations

from abc import ABC, abstractmethod

from fortress_agent.domain.action import Action
from fortress_agent.policy.context import PolicyContext


class ProtocolDependentPlugin(ABC):
    """需要已验证 wire semantics 才能启用的 Plugin 抽象标记。

    ``AttackPluginContract`` 与 ``BuildPluginContract`` 是扩展契约。生产基础实现目前
    不通过这两个 Contract 注入，而是由 CandidateGenerator + FinalValidator 组合实现；
    它们保留用于未来把协议相关能力拆成独立插件时维持 Open/Closed Principle。
    """

    plugin_id: str

    @abstractmethod
    def protocol_ready(self) -> bool:
        ...


class AttackPluginContract(ProtocolDependentPlugin):
    @abstractmethod
    def generate_attack_candidates(
        self,
        ctx: PolicyContext,
    ) -> tuple[Action, ...]:
        ...


class BuildPluginContract(ProtocolDependentPlugin):
    @abstractmethod
    def generate_build_candidates(
        self,
        ctx: PolicyContext,
    ) -> tuple[Action, ...]:
        ...
