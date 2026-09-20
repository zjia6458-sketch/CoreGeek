from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from fortress_agent.domain.state import GameState
from fortress_agent.domain.auxiliary import ExecuteCommandDecision
from fortress_agent.game_rules.tasks import active_task_record, active_task_anchor_positions


# todo(TEXT_TASK_PROMPT): 文本/自进化任务提示词的核心实现位于本文件的
# TaskSessionCoordinator._build_prompt()。后续需要人工调整提示词时，优先搜索
# “todo(TEXT_TASK_PROMPT)”定位；不要把任务提示词分散到 Runtime/HTTP 层。
_TEXT_TASK_KEYWORDS = (
    "以下文本", "下面文本", "阅读", "回答", "总结", "概括", "提取", "归纳",
    "改写", "翻译", "分类", "判断", "分析文本", "根据材料", "根据上述", "给定文本",
)
_TOOL_TASK_KEYWORDS = (
    "api", "接口", "localhost", "curl", "文件", "目录", "脚本", "配置", "部署",
    "运行", "执行命令", "shell", "token", "数据库", "http", "修复",
)


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class TaskLLMAdvice(_StrictModel):
    """任务专用 LLM 返回协议。

    LLM 只负责提出下一条 sandbox 命令或最终答案，真正是否发送仍由
    :class:`TaskSessionCoordinator` 和 FinalResponseValidator 决定。
    """

    schema_version: Literal["task-1.0"] = "task-1.0"
    source_round: int = Field(ge=1)
    action: Literal["execute", "submit", "wait"]
    execute_cmd: str = Field(default="", max_length=6000)
    task_answer: str = Field(default="", max_length=12000)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    short_reason: str = Field(default="", max_length=600)


@dataclass(frozen=True, slots=True)
class TaskTurnPlan:
    prompt: str = ""
    execute_cmd: str = ""
    session_id: str = ""
    task_answer: str = ""
    stage: str = "idle"
    reason: str = ""
    remaining_rounds: int | None = None
    anchor_zone_type: str = ""
    prior_skill_available: bool = False


@dataclass(frozen=True, slots=True)
class TaskSkillRecord:
    """同类自进化任务的跨任务成功经验。

    只保存本 Agent 实际发送过的命令轨迹，供下一任务的 LLM 参考；不会自动重放，
    因为文件路径、城市、参数、token 等都可能发生变化。
    """
    family_key: str
    successful_commands: tuple[str, ...]
    score_delta: float
    gold_delta: int
    learned_round: int


@dataclass(slots=True)
class _TaskSession:
    fingerprint: str
    family_key: str
    started_round: int
    start_score: float
    start_gold: int
    timeout_rounds: int | None = None
    anchor_zone_type: str = ""
    last_execute_cmd: str = ""
    last_execute_round: int | None = None
    last_result: str = ""
    answer_submitted: bool = False
    command_history: list[str] = field(default_factory=list)


class TaskSessionCoordinator:
    """维护 ``acceptTask -> executeCmd -> submitAnswer`` 跨回合闭环。

    设计边界：
    - ``executeCmd`` 是顶层协议字段，不是角色动作，因此不进入 CandidateRegistry；
      V0.5.5 起 Runtime 会把它包装为 ``ExecuteCommandDecision``，进入独立的
      AuxiliaryDecision -> AuxiliaryExperience -> AuxiliaryOutcome 主链；
    - ``submitAnswer`` 仍属于 Pioneer 的角色动作，Runtime 会把这里产生的答案
      交给正常 FinalResponseValidator；
    - 活跃自进化任务期间 LLM 调用官方豁免日配额，因此每回合都可以发送一个
      任务专用 prompt，让 LLM 根据 ``phaseTask + lastCmdResult`` 选择下一步；
    - 为防 LLM 缺席，首回合提供确定性的 sandbox 文件发现命令，并对少数高频
      失败提供最小修复 fallback。这里不硬编码某一道比赛题的答案。
    """

    _DISCOVER_CMD = (
        "find /tmp/selfEvolutionTask -maxdepth 6 -type f "
        "-printf '%p\\n' 2>/dev/null | sort | head -120"
    )

    def __init__(self) -> None:
        self._session: _TaskSession | None = None
        self._skills: dict[str, TaskSkillRecord] = {}
        self._last_learned_skill: TaskSkillRecord | None = None

    def plan(self, state: GameState) -> TaskTurnPlan | None:
        task_text = state.phase_task.strip()
        if not task_text:
            self._close_session(state)
            self._session = None
            return None

        fingerprint = hashlib.sha1(task_text.encode("utf-8", errors="ignore")).hexdigest()[:16]
        if self._session is None or self._session.fingerprint != fingerprint:
            task = active_task_record(state)
            anchors = active_task_anchor_positions(state)
            zone_type = ""
            if anchors:
                anchor_set = {(p.x, p.y) for p in anchors}
                zone = next((z for z in state.neutral_zones if (z.position.x, z.position.y) in anchor_set), None)
                zone_type = zone.zone_type if zone is not None else ""
            family_key = f"{task.task_type if task is not None else 'unknown'}|{zone_type or 'unknown'}"
            self._session = _TaskSession(
                fingerprint=fingerprint,
                family_key=family_key,
                started_round=state.round_id,
                start_score=state.score_self,
                start_gold=state.gold_self,
                timeout_rounds=(task.timeout_rounds if task is not None else None),
                anchor_zone_type=zone_type,
            )

        session = self._session
        remaining_rounds = (
            max(0, session.timeout_rounds - (state.round_id - session.started_round))
            if session.timeout_rounds
            else None
        )
        current_result = state.last_command_result.strip()
        if current_result:
            session.last_result = current_result

        advice = self._parse_task_advice(state.raw_llm_response)
        if advice is not None and advice.source_round < session.started_round:
            advice = None
        execute_cmd = ""
        task_answer = ""
        stage = "reason"
        reason = "task_llm_prompt"

        if advice is not None:
            if advice.action == "submit" and advice.task_answer.strip():
                task_answer = advice.task_answer.strip()
                stage = "submit"
                reason = f"llm_submit:{advice.short_reason}"
            elif advice.action == "execute" and self._safe_command(advice.execute_cmd):
                candidate = advice.execute_cmd.strip()
                # 不重复上一条完全相同的命令。重复读文件/重复 curl 会白白浪费回合。
                if candidate and candidate not in session.command_history:
                    execute_cmd = candidate
                    stage = "execute"
                    reason = f"llm_execute:{advice.short_reason}"

        if not task_answer and not execute_cmd:
            fallback = self._fallback_command(state, session)
            if fallback and fallback not in session.command_history:
                execute_cmd = fallback
                stage = "execute"
                reason = "deterministic_task_fallback"

        # 这里只“规划”命令，不提前写入 command_history。真正写入发生在
        # Runtime 完成 FinalResponseValidator 并确认 executeCmd 没有被 suppress 后。
        # 这样 TaskSkill 只学习实际准备发送的命令，而不是被验证器丢弃的计划。

        if task_answer:
            session.answer_submitted = True

        prompt = self._build_prompt(state, session)
        return TaskTurnPlan(
            prompt=prompt,
            execute_cmd=execute_cmd,
            session_id=session.fingerprint,
            task_answer=task_answer,
            stage=stage,
            reason=reason,
            remaining_rounds=remaining_rounds,
            anchor_zone_type=session.anchor_zone_type,
            prior_skill_available=session.family_key in self._skills,
        )


    def record_dispatched(self, decision: ExecuteCommandDecision) -> None:
        """记录已经通过最终协议校验、准备发送到判题器的 sandbox 命令。"""
        session = self._session
        if session is None or not decision.command.strip():
            return
        if decision.task_session_id and decision.task_session_id != session.fingerprint:
            return
        command = decision.command.strip()
        session.last_execute_cmd = command
        session.last_execute_round = decision.source_round
        if command not in session.command_history:
            session.command_history.append(command)

    def retract_dispatched(self, decision: ExecuteCommandDecision) -> None:
        """HTTP 层确认响应未送达时撤销本轮命令历史。"""
        session = self._session
        if session is None:
            return
        if decision.task_session_id and decision.task_session_id != session.fingerprint:
            return
        command = decision.command.strip()
        if session.command_history and session.command_history[-1] == command:
            session.command_history.pop()
        if session.last_execute_cmd == command and session.last_execute_round == decision.source_round:
            session.last_execute_cmd = session.command_history[-1] if session.command_history else ""
            session.last_execute_round = None

    def _close_session(self, state: GameState) -> None:
        session = self._session
        if session is None:
            return
        score_delta = float(state.score_self - session.start_score)
        gold_delta = int(state.gold_self - session.start_gold)
        # 任务结束且出现正向收益时，把实际成功轨迹保留下来。部分完成也有价值。
        if (score_delta > 0 or gold_delta > 0) and session.command_history:
            record = TaskSkillRecord(
                family_key=session.family_key,
                successful_commands=tuple(session.command_history[-12:]),
                score_delta=score_delta,
                gold_delta=gold_delta,
                learned_round=state.round_id,
            )
            self._skills[session.family_key] = record
            self._last_learned_skill = record

    def drain_last_learned_skill(self) -> TaskSkillRecord | None:
        record = self._last_learned_skill
        self._last_learned_skill = None
        return record

    def skill_for_current_session(self) -> TaskSkillRecord | None:
        if self._session is None:
            return None
        return self._skills.get(self._session.family_key)

    @staticmethod
    def _strip_fence(text: str) -> str:
        text = text.strip()
        if not text.startswith("```"):
            return text
        lines = text.splitlines()
        if len(lines) >= 3 and lines[-1].strip() == "```":
            return "\n".join(lines[1:-1]).strip()
        return text

    def _parse_task_advice(self, raw: str) -> TaskLLMAdvice | None:
        """解析任务 LLM 回复。

        Prompt 会要求模型只返回 JSON，但文本类任务中模型偶尔会先输出一句中文说明。
        这里允许从回复中提取第一个合法 JSON 对象，再执行严格 Pydantic 校验；
        这样提高容错性，但不会放宽 ``task-1.0`` 的字段协议。
        """
        if not raw or not raw.strip():
            return None
        text = self._strip_fence(raw)
        payload = None
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            decoder = json.JSONDecoder()
            for index, char in enumerate(text):
                if char != "{":
                    continue
                try:
                    candidate, _ = decoder.raw_decode(text[index:])
                except json.JSONDecodeError:
                    continue
                if isinstance(candidate, dict):
                    payload = candidate
                    break
        try:
            if not isinstance(payload, dict) or payload.get("schema_version") != "task-1.0":
                return None
            return TaskLLMAdvice.model_validate(payload)
        except (ValidationError, TypeError):
            return None

    @staticmethod
    def _task_mode_hint(task_text: str) -> str:
        """给 Prompt/Fallback 一个保守的任务类型提示。

        这不是强分类器，只用来避免纯文本题首回合无意义地执行 ``find/cat``。
        API/文件/脚本相关关键词优先级更高；无法确定时返回 ``mixed``，继续保守探索。
        """
        lowered = (task_text or "").lower()
        if any(keyword in lowered for keyword in _TOOL_TASK_KEYWORDS):
            return "tool"
        if any(keyword in lowered for keyword in _TEXT_TASK_KEYWORDS):
            return "text"
        return "mixed"

    def _fallback_command(self, state: GameState, session: _TaskSession) -> str:
        result = state.last_command_result or ""
        if not session.last_execute_cmd and not result.strip():
            # 纯文本题首先让 LLM 直接阅读 phaseTask 并回答，不要为了“看起来在工作”
            # 就执行无意义的 find/cat。未知/mixed 任务仍保留文件发现，避免漏掉沙盒材料。
            if self._task_mode_hint(state.phase_task) == "text":
                return ""
            return self._DISCOVER_CMD

        # 文件发现结果中优先阅读 API/spec/README 等说明文件。
        if result:
            paths = re.findall(r"(?m)^(/[^\r\n]+)$", result)
            # 先读具体任务文件，再读 API/spec/README。任务文件通常定义最终答案字段，
            # 先读它可以避免只懂 API 却漏掉 submitAnswer schema。
            task_paths = sorted(p for p in paths if re.search(r"/task[^/]*\.(md|txt)$", p, re.I))
            if task_paths:
                return f"cat {self._shell_quote(task_paths[0])} 2>/dev/null | head -320"
            priorities = ("API_DOCS.md", "spec.md", "README.md", "readme.md")
            for name in priorities:
                path = next((p for p in paths if p.endswith("/" + name)), None)
                if path:
                    return f"cat {self._shell_quote(path)} 2>/dev/null | head -320"

        # 高频 API 认证失败：若服务器明确要求 Bearer，则只修复认证头，不改变
        # URL/参数，符合“最小修复后重试”的任务策略。
        if (
            "Authorization" in result
            and "Bearer" in result
            and "X-API-Key" in session.last_execute_cmd
        ):
            match = re.search(r'X-API-Key:\s*([^"\']+)', session.last_execute_cmd)
            if match:
                key = match.group(1).strip()
                fixed = re.sub(
                    r'-H\s+["\']X-API-Key:\s*[^"\']+["\']',
                    f'-H "Authorization: Bearer {key}"',
                    session.last_execute_cmd,
                    count=1,
                )
                if fixed != session.last_execute_cmd:
                    return fixed

        # 任务正文经常只写相对文件名。若明确提到常见说明文件但没有绝对路径，
        # 用 find 定位后读取，而不是猜工作目录。
        for name in ("API_DOCS.md", "spec.md", "README.md"):
            if name in result:
                return (
                    f"p=$(find /tmp/selfEvolutionTask -maxdepth 6 -type f -name {self._shell_quote(name)} "
                    f"-print -quit 2>/dev/null); [ -n \"$p\" ] && cat \"$p\" | head -320"
                )

        # CRLF 脚本错误的通用最小修复，仅作用于 selfEvolutionTask 沙盒目录。
        if "bad interpreter" in result and "^M" in result:
            return (
                "find /tmp/selfEvolutionTask -maxdepth 6 -type f "
                "-name check -exec sed -i 's/\\r$//' {} +"
            )

        return ""

    @staticmethod
    def _safe_command(command: str) -> bool:
        command = (command or "").strip()
        if not command or len(command) > 6000:
            return False
        # executeCmd 本来就是任务沙盒能力，但仍拒绝明显破坏宿主/失控的命令。
        banned = (
            "rm -rf /",
            "shutdown",
            "reboot",
            "mkfs",
            ":(){:|:&};:",
        )
        return not any(token in command for token in banned)

    @staticmethod
    def _shell_quote(path: str) -> str:
        return "'" + path.replace("'", "'\\''") + "'"

    def _build_prompt(self, state: GameState, session: _TaskSession) -> str:
        # todo(TEXT_TASK_PROMPT): 这是文本/自进化任务 Prompt 的唯一主要编辑入口。
        # 任务描述目前以中文为主，因此 Prompt 也以中文组织；JSON 字段名保持协议英文。
        # 修改时优先保持：任务类型判断 -> 证据检查 -> 最小动作 -> 结果验证 -> submit。
        result = state.last_command_result.strip()
        if len(result) > 9000:
            # 保留末尾，因为 HTTP/API/脚本错误通常出现在输出最后；同时仍限制 prompt 大小。
            result = result[-9000:]
        task = state.phase_task.strip()
        if len(task) > 12000:
            task = task[:12000]
        last_cmd = session.last_execute_cmd or "<无>"
        task_mode = self._task_mode_hint(task)
        prior_skill = self._skills.get(session.family_key)
        prior_skill_text = "<无>"
        if prior_skill is not None:
            prior_skill_text = "\n".join(
                f"- {cmd}" for cmd in prior_skill.successful_commands[-8:]
            )
        remaining_rounds = (
            max(0, session.timeout_rounds - (state.round_id - session.started_round))
            if session.timeout_rounds
            else None
        )

        return f"""
你是 FortressAgent 的“自进化任务执行器”。任务描述主要使用中文，因此请用中文理解、推理和检查任务；
但最终必须严格按本 Prompt 末尾定义的 JSON 协议返回，不能输出 Markdown、代码围栏或额外解释。

【总原则】
你的目标不是“尽可能多执行命令”，而是“用最少回合得到可验证的完整答案”。每回合先判断当前证据是否已经足够：
- 如果任务原文、上一条命令输出或已有材料已经足够回答，立即 action=submit；不要为了形式继续执行 shell。
- 只有缺少完成答案所必需的信息，并且这些信息能够通过本地文件、localhost API、脚本或检查命令获得时，才 action=execute。
- 如果既不能可靠提交、也没有新的高价值命令可执行，action=wait。不要重复上一条完全相同的命令。

【先判断任务类型】
当前启发式提示：{task_mode}
这只是参考，必须以任务原文为准：
1. 文本类任务：阅读理解、信息提取、总结、分类、判断、改写、根据给定材料回答问题等。
   - 优先直接阅读“任务原文”和“lastCmdResult 中已经拿到的文本”。
   - 信息足够就直接 submit，通常不需要 executeCmd。
   - 严禁为了纯文本题无意义地 find/ls/cat；只有任务明确引用了尚未读取的文件时才读取。
2. 工具类任务：API 查询、文件/配置修复、部署、脚本执行、localhost 服务交互等。
   - 先读任务要求和相关文档，再执行一条最小验证命令。
   - 根据 lastCmdResult 做最小修复，不要一次修改多个无关因素。
3. 混合类任务：先用工具取得缺失证据，然后回到文本推理，整理并提交最终答案。

【文本任务必须执行的检查】
在 submit 前逐项完成以下检查：
1. 目标检查：任务究竟要求“回答问题、提取字段、输出 JSON、给出数字、分类还是生成文本”？不要答非所问。
2. 证据检查：答案中的每个关键事实都应来自任务原文或已获得的命令输出；缺证据时不要编造。
3. 完整性检查：逐项核对任务列出的所有问题、字段、键名、数量和约束，尤其不要漏字段。
4. 格式检查：若要求 JSON/字典/固定键名，task_answer 必须严格满足；不要在 JSON 外再加说明文字。
5. 精确性检查：注意中文实体名、大小写、数字、单位、布尔值、列表顺序和空值要求。
6. 最终答案只能放在 task_answer；short_reason 只是说明为什么执行/提交，不能把真正答案只写在 short_reason。

【工具任务闭环】
读取说明/任务文件 -> 一条最小命令验证 -> 阅读 lastCmdResult -> 只修复当前明确失败点 -> 再验证 -> 信息齐全后 submit。
可访问 localhost，但不要假设能访问外部互联网。不要机械重放历史任务命令；旧命令只能作为 SOP 思路参考。

【时间策略】
任务剩余回合较多时，允许获取必要证据；剩余回合较少时，停止低价值探索，优先整理当前最可信且字段完整的答案。

当前回合：{state.round_id}
任务会话开始回合：{session.started_round}
任务剩余回合估计：{remaining_rounds if remaining_rounds is not None else '<未知>'}
任务锚定点类型：{session.anchor_zone_type or '<未知>'}
已实际发送的 executeCmd 数量：{len(session.command_history)}

同类型任务历史成功命令（仅作 SOP 参考，必须根据当前任务改写，禁止机械重放）：
{prior_skill_text}

【任务原文】
---
{task}
---

【上一条由本 Agent 实际发送的 executeCmd】
{last_cmd}

【上一条 lastCmdResult】
---
{result or '<空>'}
---

【决策要求】
- action=execute：execute_cmd 必须是一条必要、最小、可验证的 shell 命令；task_answer 为空。
- action=submit：task_answer 必须是可直接提交的完整最终答案；execute_cmd 为空。
- action=wait：仅当当前确实没有可靠提交条件、也没有高价值下一步时使用；两个内容字段均为空。
- confidence 表示你对“本回合这个决策正确”的置信度，不是任务得分预测。

只返回一个 JSON 对象，键名和类型必须完全如下：
{{
  "schema_version":"task-1.0",
  "source_round":{state.round_id},
  "action":"execute|submit|wait",
  "execute_cmd":"当 action=execute 时给出一条 shell 命令，否则为空字符串",
  "task_answer":"当 action=submit 时给出完整最终答案，否则为空字符串",
  "confidence":0.0,
  "short_reason":"用中文简短说明为何执行、提交或等待"
}}
""".strip()
