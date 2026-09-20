from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AuxiliaryDecision:
    """顶层辅助决策的统一领域模型。

    官方协议允许一个回合同时存在三类输出：
    - ``roleCommandMap``：角色/武器动作；
    - ``prompt``：请求 LLM 的提示词；
    - ``executeCmd``：自进化任务沙盒命令。

    后两者不是 RoleAction，不能伪装成某个角色的一次动作；但它们同样需要
    decision_id、来源 node、回合号和结果归因，因此统一建模为 AuxiliaryDecision。
    具体实现见 ``PromptDecision`` / ``ExecuteCommandDecision``。
    """

    decision_id: str
    decision_type: str
    source_round: int
    source_node: str
    purpose: str = ""


@dataclass(frozen=True, slots=True)
class PromptDecision(AuxiliaryDecision):
    prompt: str = ""
    task_session_id: str = ""
    task_exempt: bool = False


@dataclass(frozen=True, slots=True)
class ExecuteCommandDecision(AuxiliaryDecision):
    command: str = ""
    task_session_id: str = ""
