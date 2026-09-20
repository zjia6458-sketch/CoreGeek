from __future__ import annotations

from dataclasses import dataclass

from .auxiliary import AuxiliaryDecision, ExecuteCommandDecision, PromptDecision
from .decision import Decision


@dataclass(frozen=True, slots=True)
class TeamDecision:
    """一个完整回合的协调决策。

    ``decisions`` 是 RoleAction 主链；``auxiliary_decisions`` 是 prompt/executeCmd
    等顶层协议决策。两者在同一回合可以并存，因此不能把 executeCmd 强行塞入
    Action 层。

    ``prompt``/``execute_cmd`` 仍保留为兼容字段，旧测试/离线工具无需立即迁移。
    生产 Runtime 从 V0.5.5 起优先构造 ``auxiliary_decisions``，编码器也优先读取
    它们。这样辅助决策拥有独立 decision_id，可进入 Outcome/Experience。
    """

    decisions: tuple[Decision, ...]
    auxiliary_decisions: tuple[AuxiliaryDecision, ...] = ()
    prompt: str = ""
    execute_cmd: str = ""

    def __post_init__(self) -> None:
        actor_ids = [str(decision.action.actor_id) for decision in self.decisions]
        if len(actor_ids) != len(set(actor_ids)):
            raise ValueError("TeamDecision contains duplicate actor ids")

        auxiliary_ids = [decision.decision_id for decision in self.auxiliary_decisions]
        if len(auxiliary_ids) != len(set(auxiliary_ids)):
            raise ValueError("TeamDecision contains duplicate auxiliary decision ids")

    def resolved_prompt(self) -> str:
        prompts = [
            d.prompt for d in self.auxiliary_decisions
            if isinstance(d, PromptDecision) and d.prompt
        ]
        return prompts[-1] if prompts else self.prompt

    def resolved_execute_cmd(self) -> str:
        commands = [
            d.command for d in self.auxiliary_decisions
            if isinstance(d, ExecuteCommandDecision) and d.command
        ]
        return commands[-1] if commands else self.execute_cmd
