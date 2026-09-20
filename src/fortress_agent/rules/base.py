from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from fortress_agent.domain.action import Action
from fortress_agent.policy.context import PolicyContext


@dataclass(frozen=True, slots=True)
class RuleResult:
    allowed: bool
    matched: bool = False
    reason: str | None = None


class Rule(ABC):
    """可插拔业务 Rule 抽象类。

    当前基础实现位于 ``rules/basic.py``。Rule 负责策略层业务约束；协议硬合法性
    由 ``policy/legal.py`` 与 ``protocol/final_validator.py`` 负责，二者不要混用。
    新 Rule 需在 ``application/basic_policy.py`` 的 RuleRegistry 注册。
    """

    rule_id: str
    priority: int = 100

    @abstractmethod
    def evaluate(
        self,
        ctx: PolicyContext,
        action: Action,
    ) -> RuleResult:
        ...


class RuleRegistry:
    def __init__(self) -> None:
        self._rules: dict[str, Rule] = {}
        self._enabled: set[str] = set()

    def register(self, rule: Rule) -> None:
        if rule.rule_id in self._rules:
            raise ValueError(f"duplicate rule: {rule.rule_id}")
        self._rules[rule.rule_id] = rule
        self._enabled.add(rule.rule_id)

    def active(self) -> tuple[Rule, ...]:
        return tuple(
            sorted(
                (
                    self._rules[rule_id]
                    for rule_id in self._enabled
                ),
                key=lambda rule: (rule.priority, rule.rule_id),
            )
        )


class BasicRuleEngine:
    def __init__(self, registry: RuleRegistry) -> None:
        self._registry = registry

    def apply(
        self,
        ctx: PolicyContext,
        actions: tuple[Action, ...],
    ) -> tuple[tuple[Action, ...], tuple[str, ...], tuple[str, ...]]:
        viable = []
        matched: list[str] = []
        rejected: list[str] = []

        for action in actions:
            allowed = True

            for rule in self._registry.active():
                result = rule.evaluate(ctx, action)

                if result.matched:
                    matched.append(rule.rule_id)

                if not result.allowed:
                    allowed = False
                    rejected.append(
                        f"{rule.rule_id}:{result.reason or 'rejected'}"
                    )
                    break

            if allowed:
                viable.append(action)

        return (
            tuple(viable),
            tuple(dict.fromkeys(matched)),
            tuple(rejected),
        )
