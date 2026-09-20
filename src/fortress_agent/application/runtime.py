from __future__ import annotations

from dataclasses import dataclass, replace

from fortress_agent.application.basic_policy import (
    BasicPolicyRuntime,
    build_basic_policy_runtime,
)
from fortress_agent.domain.decision import Decision
from fortress_agent.domain.auxiliary import PromptDecision, ExecuteCommandDecision
from fortress_agent.domain.policy_state import PolicyState
from fortress_agent.domain.reward import RewardBreakdown
from fortress_agent.domain.state import GameState
from fortress_agent.domain.action import SubmitAnswerAction
from fortress_agent.domain.team import TeamDecision
from fortress_agent.domain.utility import UtilityBreakdown
from fortress_agent.events.base import DomainEvent
from fortress_agent.learning.experience.builder import (
    ExperienceBuilder,
)
from fortress_agent.learning.experience.credit import TeamCreditAssigner
from fortress_agent.learning.experience.store import (
    CompositeExperienceStore,
    ExperienceStore,
)
from fortress_agent.learning.experience.auxiliary import (
    AuxiliaryExperienceRecord,
    AuxiliaryOutcomeRecord,
    InMemoryAuxiliaryExperienceStore,
)
from fortress_agent.learning.learners.base import (
    LearnerRegistry,
)
from fortress_agent.learning.learners.threshold import (
    PrepareMarginLearner,
)
from fortress_agent.learning.learners.utility import (
    UtilityWeightLearner,
)
from fortress_agent.learning.policy_repository import (
    InMemoryPolicyStateRepository,
)
from fortress_agent.observation.memory_engine import (
    WorldMemoryEngine,
)
from fortress_agent.memory.strategic import StrategicMemory
from fortress_agent.memory.feedback import RuntimeFeedbackMemory
from fortress_agent.memory.economy import MiningRuntimeMemory
from fortress_agent.safety.emergency import EmergencyActionUnavailable
from fortress_agent.memory.robot_trajectory import RobotTrajectoryMemory
from fortress_agent.memory.movement import MovementHistoryMemory
from fortress_agent.config.tuning import RuntimeLearningConfig
from fortress_agent.policy.build_catalog import BuildCatalog
from fortress_agent.game_rules.build_area import BuildAreaPolicy
from fortress_agent.game_rules.feedback import has_request_timeout
from fortress_agent.game_rules.economy import primary_builder_id
from fortress_agent.memory.snapshot import JsonWorldMemorySnapshotStore
from fortress_agent.llm.parser import StrategicLLMResponseParser
from fortress_agent.llm.prompt import StrategicPromptBuilder
from fortress_agent.llm.coordinator import StrategicLLMCoordinator
from fortress_agent.protocol.codec import (
    GameProtocolCodec,
)
from fortress_agent.reward.realized import (
    MemoryRewardDelta,
    RealizedRewardCalculator,
)
from fortress_agent.safety.deadline import Deadline, DeadlineExceeded
from fortress_agent.safety.llm_budget import LLMBudgetTracker
from fortress_agent.observability.trace import (
    TraceEvent,
    TraceSink,
)
from fortress_agent.observability.io import IoJournal
from fortress_agent.policy.graph.model import GraphExecutionError
from fortress_agent.protocol.server_outbound import ServerCommandResponse
from fortress_agent.tasks.session import TaskSessionCoordinator


@dataclass(frozen=True, slots=True)
class AgentTurnResult:
    ok: bool

    response_json: str | None

    game_state: GameState | None
    decision: Decision | None

    world_events: tuple[DomainEvent, ...]
    realized_reward: RewardBreakdown | None

    experience_id: str | None = None
    correlation_id: str | None = None

    error_code: str | None = None
    error_message: str | None = None


class FortressAgentRuntime:
    """单场比赛进程内的核心应用编排器。

    Runtime 不负责“某种动作应该怎样评分”这类具体业务，而负责把 Protocol、
    FeedbackMemory、WorldMemory、PolicyGraph、TeamPlanner、Encoder、Experience
    按固定顺序串起来。它持有跨回合状态，因此不能并发执行两个 handle_turn。

    生产创建位置：``application/bootstrap.py::build_runtime``。
    HTTP 调用位置：``server/http.py::HttpTurnService``。
    """

    def __init__(
        self,
        *,
        protocol: GameProtocolCodec | None = None,
        memory_engine: WorldMemoryEngine | None = None,
        policy_runtime: BasicPolicyRuntime | None = None,
        policy_state: PolicyState | None = None,
        policy_repository: InMemoryPolicyStateRepository | None = None,
        experience_store: ExperienceStore | None = None,
        learner_registry: LearnerRegistry | None = None,
        trace_sink: TraceSink | None = None,
        strategic_memory: StrategicMemory | None = None,
        feedback_memory: RuntimeFeedbackMemory | None = None,
        build_catalog: BuildCatalog | None = None,
        build_area_policy: BuildAreaPolicy | None = None,
        llm_parser: StrategicLLMResponseParser | None = None,
        llm_budget: LLMBudgetTracker | None = None,
        llm_coordinator: StrategicLLMCoordinator | None = None,
        io_journal: IoJournal | None = None,
        world_snapshot_store: JsonWorldMemorySnapshotStore | None = None,
        snapshot_interval_rounds: int = 25,
        hard_deadline_seconds: float = 3.2,
        task_session: TaskSessionCoordinator | None = None,
        runtime_learning_config: RuntimeLearningConfig | None = None,
    ) -> None:
        self._protocol = protocol or GameProtocolCodec()
        self._memory = memory_engine or WorldMemoryEngine()
        self._trace = trace_sink
        self._strategic_memory = strategic_memory or StrategicMemory()
        self._feedback_memory = feedback_memory or RuntimeFeedbackMemory()
        self._llm_parser = llm_parser or StrategicLLMResponseParser()
        self._llm_prompt_builder = StrategicPromptBuilder()
        self._llm_budget = llm_budget or LLMBudgetTracker()
        self._io_journal = io_journal
        self._world_snapshot_store = world_snapshot_store
        self._snapshot_interval_rounds = max(1, snapshot_interval_rounds)
        self._llm_coordinator = (
            llm_coordinator
            or StrategicLLMCoordinator(
                self._llm_prompt_builder
            )
        )
        self._policy = (
            policy_runtime
            or build_basic_policy_runtime(
                trace_sink=trace_sink,
                build_catalog=build_catalog,
                build_area_policy=build_area_policy,
            )
        )

        initial = policy_state or PolicyState.create()
        self._policy_repo = (
            policy_repository
            or InMemoryPolicyStateRepository(initial)
        )

        self._experiences = (
            experience_store
            or CompositeExperienceStore()
        )
        self._experience_builder = ExperienceBuilder()
        self._credit_assigner = TeamCreditAssigner()
        self._runtime_learning_config = runtime_learning_config or RuntimeLearningConfig(enabled=False)

        self._learners = (
            learner_registry
            or self._default_learners(self._runtime_learning_config)
        )

        self._reward = RealizedRewardCalculator()
        self._hard_deadline_seconds = hard_deadline_seconds
        self._task_session = task_session or TaskSessionCoordinator()
        self._mining_memory = MiningRuntimeMemory()
        self._robot_trajectory = RobotTrajectoryMemory(max_points=4)
        self._movement_history = MovementHistoryMemory(max_positions=8)
        self._next_learning_update_round = max(1, int(self._runtime_learning_config.first_update_round))
        self._round_policy_updates: list[dict[str, object]] = []

        self._previous_state: GameState | None = None
        self._pending_experiences = ()
        self._auxiliary_experiences = InMemoryAuxiliaryExperienceStore()
        self._pending_auxiliary_experiences: tuple[AuxiliaryExperienceRecord, ...] = ()
        self._turn_sequence = 0

    async def handle_turn(
        self,
        raw_response,
    ) -> AgentTurnResult:
        self._turn_sequence += 1
        self._round_policy_updates = []
        request_id = f"request:{self._turn_sequence}"

        deadline = Deadline(
            self._hard_deadline_seconds
        )

        parsed = self._protocol.parse_state(
            raw_response
        )

        if not parsed.ok:
            self._trace_emit(
                kind="request_parse_failed",
                correlation_id=request_id,
                data={
                    "error_code": parsed.error_code,
                    "message": parsed.message,
                },
            )
            if self._io_journal is not None:
                self._io_journal.record_error(
                    correlation_id=request_id,
                    error_code=(parsed.error_code or "parse_error"),
                    message=(parsed.message or "parse failed"),
                )
            return AgentTurnResult(
                ok=False,
                response_json=None,
                game_state=None,
                decision=None,
                world_events=(),
                realized_reward=None,
                correlation_id=request_id,
                error_code=parsed.error_code,
                error_message=parsed.message,
            )

        state = parsed.value
        assert state is not None
        # Robot positions are globally observable. Preserve a short real-motion
        # history before policy evaluation so night Safe A* can combine the
        # theoretical station route with the robot's actual recent heading.
        self._robot_trajectory.observe(state)
        self._movement_history.observe(state)
        correlation_id = (
            f"r{state.round_id}:attempt:{self._turn_sequence}"
        )

        if self._io_journal is not None:
            self._io_journal.record_request(
                correlation_id=correlation_id,
                round_id=state.round_id,
                raw=raw_response,
            )

        self._trace_emit(
            kind="turn_started",
            correlation_id=correlation_id,
            round_id=state.round_id,
            data={
                "day": state.day,
                "phase": state.phase,
                "policy_version": self._policy_repo.current().version,
            },
        )
        self._trace_emit(
            kind="state_parsed",
            correlation_id=correlation_id,
            round_id=state.round_id,
            data={
                "characters": len(state.characters),
                "buildings": len(state.buildings),
                "robots": len(state.enemies),
                "resources": len(state.resources),
                "server_errors": [
                    error.error_code
                    for error in state.server_errors
                ],
            },
        )
        self._llm_budget.observe_state(state)
        feedback_record = self._feedback_memory.observe(
            state,
            previous_experiences=self._pending_experiences,
        )
        self._trace_emit(
            kind="server_feedback_observed",
            correlation_id=correlation_id,
            round_id=state.round_id,
            data={
                "role_action_results": dict(feedback_record.role_action_results),
                "last_summon_treasure_result": feedback_record.last_summon_treasure_result,
                "last_command_result": feedback_record.command_result,
                "server_errors": list(feedback_record.server_errors),
            },
        )

        for failure in feedback_record.action_failures:
            self._trace_emit(
                kind="action_execution_failed",
                correlation_id=correlation_id,
                round_id=state.round_id,
                data={
                    "role_id": failure.role_id,
                    "action_type": failure.action_type,
                    "action_signature": failure.action_signature,
                    "reason": failure.reason,
                    "source": failure.source,
                    "retry_ban_until_round": failure.retry_ban_until_round,
                    "retry_scope": failure.retry_scope,
                    "move_target": (
                        [failure.move_target_x, failure.move_target_y]
                        if failure.move_target_x is not None
                        and failure.move_target_y is not None
                        else None
                    ),
                    "raw_feedback": failure.raw_feedback,
                    "command_error_signature": failure.command_error_signature,
                },
            )

        for rule in feedback_record.new_terrain_rules:
            self._trace_emit(
                kind="terrain_rule_learned",
                correlation_id=correlation_id,
                round_id=state.round_id,
                data={
                    "terrain_type": rule.terrain_type,
                    "property": rule.property_name,
                    "value": rule.property_value,
                    "scope": rule.scope,
                    "status": rule.status,
                    "validity_predicate": rule.validity_predicate,
                    "reason": rule.reason,
                    "source": rule.source,
                    "evidence_example_target": [
                        rule.evidence_target_x,
                        rule.evidence_target_y,
                    ],
                    "evidence_chain": [
                        "lastRoundRoleActionResults=false",
                        "previous_experience_exact_match",
                        "server_errors(errorCode=4).description_exact_match",
                    ],
                    "rule_signature": rule.signature,
                    "hard_rule": rule.hard_rule(),
                },
            )

        for transition in feedback_record.terrain_rule_transitions:
            self._trace_emit(
                kind="terrain_rule_lifecycle_changed",
                correlation_id=correlation_id,
                round_id=state.round_id,
                data={
                    "terrain_type": transition.terrain_type,
                    "rule_signature": transition.rule_signature,
                    "scope": transition.scope,
                    "validity_predicate": transition.validity_predicate,
                    "from_status": transition.from_status,
                    "to_status": transition.to_status,
                    "reason": transition.reason,
                },
            )

        before_discovered = self._count_discovered(
            state.map_width,
            state.map_height,
        )
        before_resources = len(
            self._memory.view().available_resources()
        )

        events = self._memory.observe(
            state,
            correlation_id=correlation_id,
        )

        after_discovered = self._count_discovered(
            state.map_width,
            state.map_height,
        )
        after_resources = len(
            self._memory.view().available_resources()
        )

        memory_delta = MemoryRewardDelta(
            newly_discovered_cells=max(
                0,
                after_discovered - before_discovered,
            ),
            newly_discovered_resources=max(
                0,
                after_resources - before_resources,
            ),
        )

        self._trace_emit(
            kind="world_memory_updated",
            correlation_id=correlation_id,
            round_id=state.round_id,
            data={
                "domain_event_count": len(events),
                "new_cells": memory_delta.newly_discovered_cells,
                "new_resources": memory_delta.newly_discovered_resources,
                "available_resources": after_resources,
            },
        )
        self._mining_memory.reconcile(state=state, world_memory=self._memory.view())
        economy_sessions = self._mining_memory.view()
        self._trace_emit(
            kind="worker_economy_sessions", correlation_id=correlation_id, round_id=state.round_id,
            data={
                "mining_targets": dict(economy_sessions.committed_resource_by_actor),
                "vendor_targets": dict(economy_sessions.vendor_by_actor),
                "phase": state.phase,
            },
        )

        realized_reward = None

        if self._previous_state is not None:
            realized_reward = self._reward.calculate(
                self._previous_state,
                state,
                memory_delta=memory_delta,
            )

            if has_request_timeout(state.server_errors):
                # 判题器明确报告上一 HTTP 请求超时，说明上一回合响应没有被可靠
                # 接收。此时不能把 pending actions 当成“已执行但 action_legal 未知”。
                # 否则 Learner 会把网络/计算超时错误归因到 MOVE/BUILD/ATTACK。
                abandoned = tuple(
                    exp.experience_id
                    for exp in self._pending_experiences
                )
                self._pending_experiences = ()
                self._pending_auxiliary_experiences = ()
                self._trace_emit(
                    kind="previous_response_timeout_observed",
                    correlation_id=correlation_id,
                    round_id=state.round_id,
                    data={
                        "abandoned_experience_ids": list(abandoned),
                        "reason": "server_reported_request_timeout",
                        "server_errors": [
                            [error.error_code, error.description]
                            for error in state.server_errors
                        ],
                    },
                )
            else:
                self._attach_pending_outcome(
                    reward=realized_reward,
                    end_round=state.round_id,
                    feedback_state=state,
                    correlation_id=correlation_id,
                )
                self._attach_pending_auxiliary_outcomes(
                    feedback_state=state,
                    correlation_id=correlation_id,
                )

        self._maybe_apply_runtime_learning(
            round_id=state.round_id,
            correlation_id=correlation_id,
        )

        self._ingest_long_horizon_information(
            state,
            correlation_id=correlation_id,
        )

        # 自进化任务是一个独立的跨回合会话。executeCmd 是顶层协议字段，
        # 不应该伪装成角色 Candidate；TaskSessionCoordinator 负责根据
        # phaseTask/lastCmdResult/任务专用 llmResp 产生下一条 sandbox 命令或
        # 最终答案。真正的 submitAnswer 仍会走 FinalResponseValidator。
        task_plan = self._task_session.plan(state)
        learned_task_skill = self._task_session.drain_last_learned_skill()
        if learned_task_skill is not None:
            self._trace_emit(
                kind="task_skill_learned",
                correlation_id=correlation_id,
                round_id=state.round_id,
                data={
                    "family_key": learned_task_skill.family_key,
                    "successful_command_count": len(learned_task_skill.successful_commands),
                    "score_delta": learned_task_skill.score_delta,
                    "gold_delta": learned_task_skill.gold_delta,
                },
            )
        if task_plan is not None:
            self._trace_emit(
                kind="task_session_planned",
                correlation_id=correlation_id,
                round_id=state.round_id,
                data={
                    "stage": task_plan.stage,
                    "reason": task_plan.reason,
                    "prompt_planned": bool(task_plan.prompt),
                    "execute_cmd_planned": bool(task_plan.execute_cmd),
                    "submit_answer_planned": bool(task_plan.task_answer),
                    "remaining_rounds": task_plan.remaining_rounds,
                    "anchor_zone_type": task_plan.anchor_zone_type,
                    "prior_skill_available": task_plan.prior_skill_available,
                },
            )

        # 从这里开始进入策略计算。若前置解析/Memory/Outcome 已经消耗了
        # 过多时间，直接返回合法空响应；5 秒异常预算比“这一回合多做一个动作”
        # 更重要。Memory 中保留本回合真实观测，但不会记录任何未发送动作。
        if deadline.remaining() < 1.15:
            return self._deadline_fallback(
                state=state,
                events=events,
                realized_reward=realized_reward,
                correlation_id=correlation_id,
                deadline=deadline,
                reason="pre_policy_budget_low",
            )

        current_policy = self._policy_repo.current()

        ctx = self._policy.context_factory.build(
            state=state,
            world_memory=self._memory.view(),
            policy_state=current_policy,
            deadline=deadline,
            strategic_memory=self._strategic_memory.view(),
            feedback_memory=self._feedback_memory.view(),
            correlation_id=correlation_id,
            mining_memory=self._mining_memory.view(),
            robot_trajectory=self._robot_trajectory.view(),
            movement_history=self._movement_history.view(),
        )

        # PolicyGraph 是可审计的控制平面。Graph 内部会在节点之间主动
        # ``await asyncio.sleep(0)``，从而让 HTTP watchdog 有机会取消超时任务。
        try:
            frame = await self._policy.graph_engine.run(ctx)
            deadline.ensure_remaining(
                0.85,
                stage="after_policy_graph",
            )
        except EmergencyActionUnavailable as exc:
            return self._deadline_fallback(
                state=state, events=events, realized_reward=realized_reward,
                correlation_id=correlation_id, deadline=deadline,
                reason=str(exc), fallback_code="safety_hold",
            )
        except (DeadlineExceeded, GraphExecutionError) as exc:
            return self._deadline_fallback(
                state=state,
                events=events,
                realized_reward=realized_reward,
                correlation_id=correlation_id,
                deadline=deadline,
                reason=f"policy_graph:{type(exc).__name__}:{exc}",
            )

        if frame.decision is None:
            raise RuntimeError(
                "policy graph ended without decision"
            )

        decision = frame.decision

        strategy_metadata = dict(
            getattr(
                frame.strategy,
                "metadata",
                {},
            )
        )
        self._trace_emit(
            kind="strategy_selected",
            correlation_id=correlation_id,
            round_id=state.round_id,
            data={
                "strategy_id": getattr(
                    frame.strategy,
                    "strategy_id",
                    None,
                ),
                "candidate_tags": sorted(
                    getattr(
                        frame.strategy,
                        "candidate_tags",
                        (),
                    )
                ),
                "metadata": strategy_metadata,
            },
        )

        self._trace_emit(
            kind="control_decision_selected",
            correlation_id=correlation_id,
            round_id=state.round_id,
            data={
                "actor_id": str(decision.action.actor_id),
                "action_type": decision.action.action_type,
                "strategy_id": decision.strategy_id,
                "utility": decision.utility.total,
                "candidate_count": len(frame.candidates),
                "legal_count": len(frame.legal_actions),
                "viable_count": len(frame.viable_actions),
            },
        )

        safety_revision_key = (
            "|".join([
                *(
                    rule.signature
                    for rule in feedback_record.new_terrain_rules
                ),
                *(
                    f"{transition.rule_signature}:"
                    f"{transition.from_status}->{transition.to_status}"
                    for transition in feedback_record.terrain_rule_transitions
                ),
                *(
                    failure.signature
                    for failure in feedback_record.action_failures
                ),
            ])
            or None
        )
        planned_llm = self._llm_coordinator.plan(
            state=state,
            memory=self._strategic_memory.view(),
            budget=self._llm_budget,
            learned_hard_rules=self._feedback_memory.view().hard_rules(),
            safety_revision_key=safety_revision_key,
        )
        # 顶层协议行为不再作为字符串旁路，而是进入 AuxiliaryDecision 主链。
        # RoleAction 与 prompt/executeCmd 可以同回合并存，因此后者不能继承 Action。
        auxiliary_decisions = []
        if task_plan is not None and task_plan.prompt:
            auxiliary_decisions.append(PromptDecision(
                decision_id=f"{correlation_id}:aux:task_prompt",
                decision_type="prompt",
                source_round=state.round_id,
                source_node="task_session",
                purpose="self_evolution_task",
                prompt=task_plan.prompt,
                task_session_id=task_plan.session_id,
                task_exempt=True,
            ))
        elif planned_llm is not None and planned_llm.prompt:
            auxiliary_decisions.append(PromptDecision(
                decision_id=f"{correlation_id}:aux:strategic_prompt",
                decision_type="prompt",
                source_round=state.round_id,
                source_node="llm_coordinator",
                purpose="strategic_advisory",
                prompt=planned_llm.prompt,
                task_exempt=False,
            ))
        if task_plan is not None and task_plan.execute_cmd:
            auxiliary_decisions.append(ExecuteCommandDecision(
                decision_id=f"{correlation_id}:aux:execute_cmd",
                decision_type="execute_cmd",
                source_round=state.round_id,
                source_node="task_session",
                purpose="self_evolution_task",
                command=task_plan.execute_cmd,
                task_session_id=task_plan.session_id,
            ))
        auxiliary_decisions = tuple(auxiliary_decisions)

        # 真实协议允许一回合多角色联合动作。这里**复用** PolicyGraph 已经
        # 生成并通过 Legal/Rule 的 viable_actions，禁止再次完整生成 Candidate。
        # 旧实现重复执行 A*，在资源较多时会显著放大回合延迟。
        team_decision = (
            self._policy.team_planner.plan_from_viable(
                ctx,
                strategy=frame.strategy,
                viable_actions=frame.viable_actions,
                matched_rules=frame.matched_rules,
                rejected_reasons=frame.rejected_reasons,
                auxiliary_decisions=auxiliary_decisions,
            )
            if self._policy.team_planner is not None
            else None
        )

        # PolicyGraph 可能通过 EmergencyNode 选出一个确定性安全动作，而
        # frame.viable_actions 仍为空。旧实现随后用空 viable 重新做 TeamPlanner，
        # 把 emergency control decision 丢掉，最终 roleCommandMap={}。夜间连续
        # 空响应的一个直接原因就在这里。仅当团队规划完全为空时恢复 graph
        # 已经 Validate 过的 control decision。
        if team_decision is not None and not team_decision.decisions:
            team_decision = TeamDecision(
                decisions=(decision,),
                auxiliary_decisions=team_decision.auxiliary_decisions,
            )
            self._trace_emit(
                kind="team_empty_control_fallback",
                correlation_id=correlation_id,
                round_id=state.round_id,
                data={
                    "actor_id": str(decision.action.actor_id),
                    "action_type": decision.action.action_type,
                    "strategy_id": decision.strategy_id,
                },
            )

        # TaskSession 给出最终答案时，Pioneer 的 submitAnswer 应覆盖本回合
        # 可能选中的 MOVE/USE 等普通动作。这里不绕过 FinalResponseValidator：
        # 只是把任务动作放进 TeamDecision，编码前仍执行完整协议合法性校验。
        if (
            team_decision is not None
            and task_plan is not None
            and task_plan.task_answer
        ):
            pioneer = next(
                (actor for actor in state.characters if actor.role == "pioneer"),
                None,
            )
            if pioneer is not None:
                submit = Decision(
                    action=SubmitAnswerAction(
                        actor_id=pioneer.actor_id,
                        action_type="submitAnswer",
                        task_answer=task_plan.task_answer,
                    ),
                    strategy_id="active_task",
                    utility=UtilityBreakdown(future=100.0, total=100.0),
                    matched_rules=("task_session_final_answer",),
                    rejected_reasons=(),
                    policy_version=current_policy.version,
                )
                team_decision = TeamDecision(
                    decisions=tuple(
                        d for d in team_decision.decisions
                        if str(d.action.actor_id) != str(pioneer.actor_id)
                    ) + (submit,),
                    auxiliary_decisions=tuple(
                        aux for aux in team_decision.auxiliary_decisions
                        if not isinstance(aux, ExecuteCommandDecision)
                    ),
                )

        if deadline.remaining() < 0.50:
            return self._deadline_fallback(
                state=state,
                events=events,
                realized_reward=realized_reward,
                correlation_id=correlation_id,
                deadline=deadline,
                reason="post_team_planner_budget_low",
            )

        actual_decisions = (decision,)

        if team_decision is not None:
            self._trace_emit(
                kind="team_decision_planned",
                correlation_id=correlation_id,
                round_id=state.round_id,
                data={
                    "decision_count": len(team_decision.decisions),
                    "actions": [
                        {
                            "actor_id": str(item.action.actor_id),
                            "action_type": item.action.action_type,
                            "utility": item.utility.total,
                            "strategy_id": item.strategy_id,
                            "matched_rules": list(item.matched_rules),
                            "action_repr": repr(item.action),
                        }
                        for item in team_decision.decisions
                    ],
                    "prompt_planned": bool(team_decision.resolved_prompt()),
                    "auxiliary_decisions": [
                        {
                            "decision_id": aux.decision_id,
                            "decision_type": aux.decision_type,
                            "source_node": aux.source_node,
                        }
                        for aux in team_decision.auxiliary_decisions
                    ],
                },
            )

        actual_auxiliary_decisions = ()

        if team_decision is not None:
            detailed = self._policy.encoder.encode_team_detailed(
                team_decision,
                state=state,
                world_memory=self._memory.view(),
                feedback_memory=self._feedback_memory.view(),
                llm_call_allowed=self._llm_budget.can_call(state),
            )

            if not detailed.ok:
                return AgentTurnResult(
                    ok=False,
                    response_json=None,
                    game_state=state,
                    decision=decision,
                    world_events=events,
                    realized_reward=realized_reward,
                    error_code=detailed.error_code,
                    error_message=detailed.message,
                )

            encoded_json = detailed.json

            if (
                planned_llm is not None
                and not detailed.suppressed_prompt
            ):
                self._llm_budget.record_call(
                    state,
                    task_exempt=False,
                )
                self._llm_coordinator.mark_sent(
                    planned_llm
                )

            accepted = set(detailed.accepted_role_ids)
            self._trace_emit(
                kind="final_response_validated",
                correlation_id=correlation_id,
                round_id=state.round_id,
                data={
                    "accepted_role_ids": list(detailed.accepted_role_ids),
                    "rejected_role_ids": list(detailed.rejected_role_ids),
                    "prompt_suppressed": detailed.suppressed_prompt,
                    "execute_cmd_suppressed": detailed.suppressed_execute_cmd,
                },
            )
            actual_decisions = tuple(
                d
                for d in team_decision.decisions
                if str(d.action.actor_id) in accepted
            )
            actual_auxiliary_decisions = tuple(
                aux for aux in team_decision.auxiliary_decisions
                if not (isinstance(aux, PromptDecision) and detailed.suppressed_prompt)
                and not (isinstance(aux, ExecuteCommandDecision) and detailed.suppressed_execute_cmd)
            )
            for aux in actual_auxiliary_decisions:
                if isinstance(aux, ExecuteCommandDecision):
                    self._task_session.record_dispatched(aux)
        else:
            encoded = self._policy.encoder.encode(
                decision,
                state=state,
                world_memory=self._memory.view(),
                prompt=(
                    next((aux.prompt for aux in auxiliary_decisions if isinstance(aux, PromptDecision)), "")
                ),
                llm_call_allowed=self._llm_budget.can_call(state),
            )

            if not encoded.ok:
                return AgentTurnResult(
                    ok=False,
                    response_json=None,
                    game_state=state,
                    decision=decision,
                    world_events=events,
                    realized_reward=realized_reward,
                    error_code=encoded.error_code,
                    error_message=encoded.message,
                )

            encoded_json = encoded.value

            if (
                planned_llm is not None
                and any(isinstance(aux, PromptDecision) for aux in auxiliary_decisions)
            ):
                self._llm_budget.record_call(
                    state,
                    task_exempt=False,
                )
                self._llm_coordinator.mark_sent(
                    planned_llm
                )

        # Experience 表示“准备作为最终响应发送的动作”。提交前再次保留
        # response reserve；若预算已不足，就不要把尚未送达判题器的动作写进
        # pending experience。
        if deadline.remaining() < 0.25:
            return self._deadline_fallback(
                state=state,
                events=events,
                realized_reward=realized_reward,
                correlation_id=correlation_id,
                deadline=deadline,
                reason="pre_experience_commit_budget_low",
            )

        experiences = tuple(
            self._experience_builder.build_decision(
                ctx=ctx,
                decision=actual_decision,
                action_probability=1.0,
            )
            for actual_decision in actual_decisions
        )

        for experience in experiences:
            self._experiences.append(experience)
            self._trace_emit(
                kind="experience_recorded",
                correlation_id=correlation_id,
                round_id=state.round_id,
                data={
                    "experience_id": experience.experience_id,
                    "decision_id": experience.decision_id,
                    "actor_id": str(experience.action.actor_id),
                    "action_type": experience.action.action_type,
                    "predicted_utility": experience.predicted_utility.total,
                },
            )

        self._pending_experiences = experiences

        auxiliary_experiences = tuple(
            AuxiliaryExperienceRecord(
                experience_id=f"auxexp:{aux.decision_id}",
                decision_id=aux.decision_id,
                round_id=state.round_id,
                strategy_id=getattr(frame.strategy, "strategy_id", "unknown"),
                decision=aux,
                correlation_id=correlation_id,
            )
            for aux in actual_auxiliary_decisions
        )
        for aux_exp in auxiliary_experiences:
            self._auxiliary_experiences.append(aux_exp)
            self._trace_emit(
                kind="auxiliary_experience_recorded",
                correlation_id=correlation_id,
                round_id=state.round_id,
                data={
                    "experience_id": aux_exp.experience_id,
                    "decision_id": aux_exp.decision_id,
                    "decision_type": aux_exp.decision.decision_type,
                    "source_node": aux_exp.decision.source_node,
                },
            )
        self._pending_auxiliary_experiences = auxiliary_experiences

        experience = (
            experiences[0]
            if experiences
            else None
        )

        self._previous_state = state

        if (
            self._world_snapshot_store is not None
            and state.round_id % self._snapshot_interval_rounds == 0
        ):
            self._memory.snapshot_to(
                self._world_snapshot_store,
                round_id=state.round_id,
            )
            self._trace_emit(
                kind="world_snapshot_saved",
                correlation_id=correlation_id,
                round_id=state.round_id,
                data={"round_id": state.round_id},
            )

        self._emit_turn_trace(
            state=state,
            decision=decision,
            event_count=len(events),
            realized_reward=realized_reward,
            deadline=deadline,
            correlation_id=correlation_id,
        )

        if self._io_journal is not None:
            self._io_journal.record_response(
                correlation_id=correlation_id,
                round_id=state.round_id,
                raw_json=encoded_json,
            )

        self._emit_human_round_summary(
            state=state,
            frame=frame,
            actual_decisions=actual_decisions,
            actual_auxiliary_decisions=actual_auxiliary_decisions,
            task_plan=task_plan,
            deadline=deadline,
            correlation_id=correlation_id,
        )

        return AgentTurnResult(
            ok=True,
            response_json=encoded_json,
            game_state=state,
            decision=decision,
            world_events=events,
            realized_reward=realized_reward,
            experience_id=(
                experience.experience_id
                if experience is not None
                else None
            ),
            correlation_id=correlation_id,
        )

    def _emit_human_round_summary(
        self,
        *,
        state: GameState,
        frame,
        actual_decisions,
        actual_auxiliary_decisions,
        task_plan,
        deadline: Deadline,
        correlation_id: str,
    ) -> None:
        """发出“一回合一屏”的人类复盘摘要。

        原始结构化 trace/experience 仍然保留；这个事件只是 human-facing
        projection，尤其用于快速查看 node 链、资金、分数、单位位置和最终动作。
        """
        if self._trace is None:
            return

        roles = [
            {
                "kind": actor.role,
                "id": str(actor.actor_id),
                "x": actor.position.x,
                "y": actor.position.y,
                "hp": actor.hp,
            }
            for actor in state.characters
        ]
        buildings = [
            {
                "kind": building.building_type,
                "id": str(building.building_id),
                "x": building.position.x,
                "y": building.position.y,
                "hp": building.hp,
                "level": building.level,
            }
            for building in state.buildings
            if building.owner == "self"
        ]
        actions = [
            {
                "actor_id": str(decision.action.actor_id),
                "action_type": decision.action.action_type,
                "action_repr": repr(decision.action),
                "detail": self._human_action_detail(decision.action),
                "utility": decision.utility.total,
                "utility_formula": decision.utility.formula,
                "utility_raw": dict(decision.utility.raw_components),
                "utility_weights": dict(decision.utility.effective_weights),
                "resource_formula": self._resource_formula_for_decision(state, decision),
            }
            for decision in actual_decisions
        ]

        self._trace.emit(
            TraceEvent(
                kind="round_human_summary",
                round_id=state.round_id,
                correlation_id=correlation_id,
                data={
                    "day": state.day,
                    "phase": state.phase.upper(),
                    "gold": state.gold_self,
                    "score": state.score_self,
                    "strategy": getattr(frame.strategy, "strategy_id", None),
                    "node_chain": list(frame.node_chain),
                    "roles": roles,
                    "buildings": buildings,
                    "actions": actions,
                    "execute_cmd": next((
                        aux.command for aux in actual_auxiliary_decisions
                        if isinstance(aux, ExecuteCommandDecision)
                    ), ""),
                    "task_stage": (task_plan.stage if task_plan is not None else ""),
                    "task_remaining_rounds": (task_plan.remaining_rounds if task_plan is not None else None),
                    "task_anchor_zone_type": (task_plan.anchor_zone_type if task_plan is not None else ""),
                    "last_cmd_result": state.last_command_result,
                    "economy_roles": {
                        str(actor.actor_id): (
                            "主建设者" if actor.role == "worker" and str(actor.actor_id) == primary_builder_id(state)
                            else "矿工" if actor.role == "worker"
                            else "开拓者"
                        )
                        for actor in state.characters
                    },
                    "deadline_remaining": round(deadline.remaining(), 3),
                    "policy_updates": list(self._round_policy_updates),
                    # 每回合末尾都把当前 Learned Overlay 打进人类日志。由于比赛环境
                    # 只能下载 stdout，这个快照就是复盘时恢复“学到了什么”的唯一来源。
                    "learned_overlay": list(self._policy_repo.learned_overlay_snapshot()),
                },
            )
        )

    @staticmethod
    def _human_action_detail(action) -> str:
        action_type = str(getattr(action, "action_type", type(action).__name__))
        if hasattr(action, "target") and getattr(action, "target") is not None:
            target = getattr(action, "target")
            name = getattr(action, "name", "")
            suffix = f" {name}" if name else ""
            return f"{action_type}{suffix} -> ({target.x},{target.y})"
        if hasattr(action, "x") and hasattr(action, "y"):
            detail = f"{action_type} -> ({getattr(action, 'x')},{getattr(action, 'y')})"
            goal_kind = getattr(action, "goal_kind", "")
            if goal_kind:
                detail += f" [goal:{goal_kind}]"
            resource_id = getattr(action, "resource_id", "")
            if resource_id:
                detail += f" [resource:{resource_id}]"
            return detail
        targets = getattr(action, "targets", None)
        if targets:
            points = ",".join(f"({p.x},{p.y})" for p in targets)
            return f"{action_type} -> {points}"
        if action_type == "submitAnswer":
            return "submitAnswer"
        name = getattr(action, "name", "")
        if name:
            return f"{action_type} {name}"
        return action_type

    def _deadline_fallback(
        self,
        *,
        state: GameState,
        events: tuple[DomainEvent, ...],
        realized_reward: RewardBreakdown | None,
        correlation_id: str,
        deadline: Deadline,
        reason: str,
        fallback_code: str = "deadline_fallback",
    ) -> AgentTurnResult:
        """预算不足或没有已验证安全动作时返回协议合法的空动作响应。

        这里不是异常恢复，而是主动的 deadline degradation。
        本回合已经收到的世界观测仍然保留；由于没有向判题器发送角色动作，
        ``_pending_experiences`` 必须清空，避免下一回合把未发送动作错误归因。
        """

        self._pending_experiences = ()
        self._pending_auxiliary_experiences = ()
        self._previous_state = state

        encoded = self._protocol.serialize_server_response(
            ServerCommandResponse()
        )
        response_json = (
            encoded.value
            if encoded.ok and encoded.value is not None
            else '{"roleCommandMap":{},"prompt":"","executeCmd":""}'
        )

        self._trace_emit(
            kind=fallback_code,
            correlation_id=correlation_id,
            round_id=state.round_id,
            data={
                "reason": reason,
                "elapsed_seconds": deadline.elapsed(),
                "remaining_seconds": deadline.remaining(),
                "response":"safe_empty",
            },
        )

        if self._io_journal is not None:
            self._io_journal.record_response(
                correlation_id=correlation_id,
                round_id=state.round_id,
                raw_json=response_json,
            )

        return AgentTurnResult(
            ok=True,
            response_json=response_json,
            game_state=state,
            decision=None,
            world_events=events,
            realized_reward=realized_reward,
            experience_id=None,
            correlation_id=correlation_id,
            error_code=fallback_code,
            error_message=reason,
        )

    def abandon_undelivered_response(
        self,
        correlation_id: str | None,
    ) -> None:
        """HTTP 层确认响应未送达时撤销“待归因动作”。

        BrokenPipe/outer watchdog 发生后，判题器并没有收到本轮动作。如果仍把
        这些动作留在 ``_pending_experiences``，下一回合的
        ``lastRoundRoleActionResults`` 会被错误地归因给它们。

        Experience Store 中已经写入的历史记录不删除；它们保留为未完成记录，
        但不会再进入下一回合的 Outcome 绑定。
        """

        if not correlation_id:
            return
        if self._pending_experiences and all(
            exp.correlation_id == correlation_id
            for exp in self._pending_experiences
        ):
            self._pending_experiences = ()
        if self._pending_auxiliary_experiences and all(
            exp.correlation_id == correlation_id
            for exp in self._pending_auxiliary_experiences
        ):
            for exp in self._pending_auxiliary_experiences:
                if isinstance(exp.decision, ExecuteCommandDecision):
                    self._task_session.retract_dispatched(exp.decision)
            self._pending_auxiliary_experiences = ()

        self._trace_emit(
            kind="response_delivery_abandoned",
            correlation_id=correlation_id,
            round_id=(
                self._previous_state.round_id
                if self._previous_state is not None
                else None
            ),
            data={
                "reason":"http_response_not_delivered",
                "pending_experiences_cleared": True,
            },
        )

    def propose_policy_patches(self):
        current = self._policy_repo.current()
        proposals = []

        for learner in self._learners.all():
            patch = learner.propose(current)
            if patch is not None:
                proposals.append(patch)

        return tuple(proposals)

    def create_candidate(
        self,
        patch,
    ) -> PolicyState:
        return self._policy_repo.create_candidate(
            patch
        )

    def promote_candidate(
        self,
        version: int,
    ) -> None:
        self._policy_repo.promote(version)

    def rollback(
        self,
        version: int,
    ) -> None:
        self._policy_repo.rollback(version)

    def _attach_pending_outcome(
        self,
        *,
        reward: RewardBreakdown,
        end_round: int,
        feedback_state: GameState,
        correlation_id: str,
    ) -> None:
        if not self._pending_experiences:
            return

        legality = dict(
            feedback_state.last_round_role_action_results
        )

        assigned = self._credit_assigner.assign(
            experiences=self._pending_experiences,
            reward=reward,
            legality=legality,
        )

        for experience, assigned_reward, legal in assigned:
            outcome, credit = (
                self._experience_builder.build_outcome(
                    previous=experience,
                    reward=assigned_reward,
                    end_round=end_round,
                    action_legal=legal,
                    server_error_codes=tuple(
                        error.error_code
                        for error in feedback_state.server_errors
                    ),
                    server_error_messages=tuple(
                        error.description
                        for error in feedback_state.server_errors
                    ),
                    command_error_signatures=tuple(
                        lesson.signature
                        for lesson in (
                            self._feedback_memory.view().latest().command_errors
                            if self._feedback_memory.view().latest() is not None
                            else ()
                        )
                    ),
                    terrain_rule_signatures=tuple(
                        rule.signature
                        for rule in (
                            self._feedback_memory.view().latest().new_terrain_rules
                            if self._feedback_memory.view().latest() is not None
                            else ()
                        )
                    ),
                    action_failure_signatures=tuple(
                        failure.signature
                        for failure in (
                            self._feedback_memory.view().latest().action_failures
                            if self._feedback_memory.view().latest() is not None
                            else ()
                        )
                        if failure.role_id == str(experience.action.actor_id)
                    ),
                    summon_treasure_result=(
                        feedback_state.last_summon_treasure_result
                    ),
                    execute_cmd_result=(
                        feedback_state.last_command_result
                    ),
                    correlation_id=correlation_id,
                )
            )

            self._experiences.attach_outcome(
                outcome,
                (credit,),
            )

            self._trace_emit(
                kind="outcome_attached",
                correlation_id=correlation_id,
                round_id=end_round,
                data={
                    "experience_id": experience.experience_id,
                    "decision_id": experience.decision_id,
                    "outcome_id": outcome.outcome_id,
                    "action_legal": outcome.action_legal,
                    "realized_reward": outcome.reward.total,
                    "server_error_codes": list(outcome.server_error_codes),
                },
            )

            for learner in self._learners.all():
                learner.observe(
                    experience,
                    outcome,
                )

            if legal is not False and self._previous_state is not None:
                emergency_rounds = int(
                    self._policy_repo.current().thresholds.get("mining_emergency_rounds", 8.0)
                )
                self._mining_memory.record_confirmed_action(
                    state=self._previous_state,
                    action=experience.action,
                    emergency_rounds=emergency_rounds,
                )

    @property
    def auxiliary_experience_store(self):
        return self._auxiliary_experiences

    def _attach_pending_auxiliary_outcomes(
        self,
        *,
        feedback_state: GameState,
        correlation_id: str,
    ) -> None:
        if not self._pending_auxiliary_experiences:
            return
        for record in self._pending_auxiliary_experiences:
            decision = record.decision
            result_text = ""
            llm_response = ""
            transport_success = None
            if isinstance(decision, ExecuteCommandDecision):
                result_text = feedback_state.last_command_result or ""
                stripped = result_text.lstrip()
                if stripped.startswith("[exitCode:0]"):
                    transport_success = True
                elif stripped.startswith("[exitCode:") or stripped.startswith("[TIMEOUT]"):
                    transport_success = False
            elif isinstance(decision, PromptDecision):
                llm_response = feedback_state.raw_llm_response or ""
                transport_success = bool(llm_response.strip())

            outcome = AuxiliaryOutcomeRecord(
                outcome_id=f"auxoutcome:{record.decision_id}:{feedback_state.round_id}",
                decision_id=record.decision_id,
                start_round=record.round_id,
                end_round=feedback_state.round_id,
                result_text=result_text,
                llm_response=llm_response,
                transport_success=transport_success,
                correlation_id=correlation_id,
            )
            self._auxiliary_experiences.attach(outcome)
            self._trace_emit(
                kind="auxiliary_outcome_attached",
                correlation_id=correlation_id,
                round_id=feedback_state.round_id,
                data={
                    "decision_id": record.decision_id,
                    "decision_type": decision.decision_type,
                    "transport_success": transport_success,
                    "result_present": bool(result_text),
                    "llm_response_present": bool(llm_response),
                },
            )
        self._pending_auxiliary_experiences = ()

    @staticmethod
    def _default_learners(config: RuntimeLearningConfig):
        registry = LearnerRegistry()
        registry.register(PrepareMarginLearner(
            min_samples=config.prepare_min_samples,
            step=config.prepare_step_rounds,
            minimum=config.prepare_min_rounds,
            maximum=config.prepare_max_rounds,
            negative_reward_threshold=config.prepare_negative_reward_threshold,
            positive_reward_threshold=config.prepare_positive_reward_threshold,
        ))
        registry.register(UtilityWeightLearner(
            min_samples=config.economy_min_samples,
            learning_rate=config.economy_learning_rate,
            minimum=config.economy_multiplier_min,
            maximum=config.economy_multiplier_max,
            error_deadband=config.economy_error_deadband,
        ))
        return registry

    def _current_patch_value(self, state: PolicyState, component: str, key: str) -> float | None:
        if component == "thresholds":
            return float(state.thresholds.get(key)) if key in state.thresholds else None
        if component == "utility_weights":
            return float(state.utility_weights.get(key)) if key in state.utility_weights else None
        if component == "parameters":
            return float(state.parameters.get(key)) if key in state.parameters else None
        if component == "strategy_priors":
            return float(state.strategy_priors.get(key)) if key in state.strategy_priors else None
        if component == "risk_weight":
            return float(state.risk_weight)
        return None

    def _maybe_apply_runtime_learning(self, *, round_id: int, correlation_id: str) -> None:
        cfg = self._runtime_learning_config
        if not cfg.enabled or round_id < self._next_learning_update_round:
            return
        interval = max(1, int(cfg.update_interval_rounds))
        while self._next_learning_update_round <= round_id:
            self._next_learning_update_round += interval

        proposals = sorted(
            self.propose_policy_patches(),
            key=lambda p: (-float(p.confidence), p.proposer, p.key),
        )
        applied = 0
        allowed = {
            ("thresholds", "prepare_margin_rounds"),
            ("utility_weights", "economy"),
        }
        for proposal in proposals:
            if applied >= max(0, int(cfg.max_patches_per_update)):
                break
            if (proposal.component, proposal.key) not in allowed:
                continue
            if proposal.confidence < cfg.min_confidence:
                continue
            current = self._policy_repo.current()
            old = self._current_patch_value(current, proposal.component, proposal.key)
            base_value = current.base_value(proposal.component, proposal.key)
            if old is None or base_value is None or abs(base_value) < 1e-12:
                continue

            desired_delta = float(proposal.new_value) - old
            # 学习步长同时受“Base 的相对比例”和绝对值限制。这里故意使用 Base 而不是
            # 当前 Effective：这样无论历史 Overlay 已经积累多少，每一步允许改变的幅度
            # 都以人工基线为稳定参照。
            max_delta = min(
                float(cfg.max_absolute_change),
                abs(base_value) * float(cfg.max_relative_change),
            )
            if max_delta <= 0:
                continue
            delta = max(-max_delta, min(max_delta, desired_delta))
            if abs(delta) < 1e-12:
                continue

            old_overlay_ratio = current.overlay_ratio(proposal.component, proposal.key)
            patch = replace(
                proposal,
                parent_version=current.version,
                old_value=old,
                new_value=old + delta,
            )
            candidate = self._policy_repo.create_candidate(patch)
            self._policy_repo.promote(candidate.version)
            new_overlay_ratio = candidate.overlay_ratio(patch.component, patch.key)
            update = {
                "round_id": round_id,
                "policy_version": candidate.version,
                "component": patch.component,
                "key": patch.key,
                "base_value": base_value,
                "old_value": old,
                "new_value": patch.new_value,
                "old_overlay_ratio": old_overlay_ratio,
                "new_overlay_ratio": new_overlay_ratio,
                "overlay_value": base_value * new_overlay_ratio,
                "proposer": patch.proposer,
                "confidence": patch.confidence,
                "reason": patch.reason,
                "next_update_round": self._next_learning_update_round,
                # 更新事件自身也携带完整快照；HIGH 日志可独立还原当前学习状态。
                "learned_overlay": list(candidate.overlay_snapshot()),
            }
            self._round_policy_updates.append(update)
            self._trace_emit(
                kind="runtime_policy_updated",
                correlation_id=correlation_id,
                round_id=round_id,
                data=update,
            )
            applied += 1

    def _resource_formula_for_decision(self, state: GameState, decision) -> str:
        from fortress_agent.domain.action import ResourceApproachAction
        from fortress_agent.game_rules.economy import resource_selection_score
        action = decision.action
        if not isinstance(action, ResourceApproachAction):
            return ""
        actor = next((a for a in state.characters if a.actor_id == action.actor_id), None)
        resource = self._memory.view().resource(action.resource_id)
        if actor is None or resource is None:
            return ""
        current = self._policy_repo.current()
        ctx = self._policy.context_factory.build(
            state=state, world_memory=self._memory.view(), policy_state=current,
            deadline=Deadline(0.01), strategic_memory=self._strategic_memory.view(),
            feedback_memory=self._feedback_memory.view(), mining_memory=self._mining_memory.view(),
            robot_trajectory=self._robot_trajectory.view(),
            movement_history=self._movement_history.view(),
        )
        distance = max(abs(actor.position.x-resource.x), abs(actor.position.y-resource.y))
        _, _, formula = resource_selection_score(ctx, actor, resource, distance=distance)
        return formula


    def _ingest_long_horizon_information(
        self,
        state: GameState,
        *,
        correlation_id: str,
    ) -> None:
        if (
            state.world_news is not None
            and state.world_news.folk_legends
        ):
            is_new = self._strategic_memory.observe_lore(
                round_id=state.round_id,
                text=state.world_news.folk_legends,
            )

            if is_new and self._trace is not None:
                self._trace.emit(
                    TraceEvent(
                        kind="folk_legend_observed",
                        round_id=state.round_id,
                        correlation_id=correlation_id,
                        data={
                            "text": state.world_news.folk_legends,
                        },
                    )
                )

        if not state.raw_llm_response.strip():
            return

        # 活跃自进化任务期间 llmResp 使用 task-1.0 专用协议，由
        # TaskSessionCoordinator 消费；不能再把它当 StrategicAdvisory 解析。
        if state.phase_task.strip():
            return

        parsed = self._llm_parser.parse(
            state.raw_llm_response
        )

        if parsed.ok and parsed.value is not None:
            # Prevent stale/mismatched LLM responses from silently controlling
            # current strategy.
            advisory = parsed.value
            if advisory.source_round > state.round_id:
                if self._trace is not None:
                    self._trace.emit(
                        TraceEvent(
                            kind="llm_advisory_rejected",
                            round_id=state.round_id,
                            data={
                                "reason": "source_round_in_future",
                                "source_round": advisory.source_round,
                            },
                        )
                    )
                return

            self._strategic_memory.add_advisory(
                advisory
            )

            if self._trace is not None:
                self._trace.emit(
                    TraceEvent(
                        kind="llm_advisory_accepted",
                        round_id=state.round_id,
                        correlation_id=correlation_id,
                        data={
                            "recommended_mode": advisory.recommended_mode,
                            "confidence": advisory.confidence,
                            "mode_strength": advisory.mode_strength,
                        },
                    )
                )
        elif self._trace is not None:
            self._trace.emit(
                TraceEvent(
                    kind="llm_advisory_rejected",
                    round_id=state.round_id,
                    data={
                        "error_code": parsed.error_code,
                        "message": parsed.message,
                    },
                )
            )

    def build_strategic_llm_prompt(
        self,
        state: GameState,
    ) -> str:
        return self._llm_prompt_builder.build(
            state,
            learned_hard_rules=self._feedback_memory.view().hard_rules(),
        )

    def _count_discovered(
        self,
        width: int = 41,
        height: int = 32,
    ) -> int:
        memory = self._memory.view()
        count = 0

        for y in range(height):
            for x in range(width):
                if memory.cell(
                    x,
                    y,
                ).discovered:
                    count += 1

        return count

    def _emit_turn_trace(
        self,
        *,
        state,
        decision,
        event_count,
        realized_reward,
        deadline,
        correlation_id,
    ) -> None:
        if self._trace is None:
            return

        self._trace.emit(
            TraceEvent(
                kind="turn_completed",
                round_id=state.round_id,
                correlation_id=correlation_id,
                event_id=f"{correlation_id}:turn_completed",
                data={
                    "strategy": decision.strategy_id,
                    "action_type": decision.action.action_type,
                    "expected_utility": decision.utility.total,
                    "event_count": event_count,
                    "realized_reward": (
                        None
                        if realized_reward is None
                        else realized_reward.total
                    ),
                    "policy_version": (
                        decision.policy_version
                    ),
                    "deadline_remaining": (
                        deadline.remaining()
                    ),
                },
            )
        )


    def can_request_llm(
        self,
        state: GameState,
    ) -> bool:
        return self._llm_budget.can_call(state)

    def record_llm_request(
        self,
        state: GameState,
    ) -> None:
        self._llm_budget.record_call(state)

    @property
    def llm_budget(self):
        return self._llm_budget.view()

    def _trace_emit(
        self,
        *,
        kind: str,
        correlation_id: str,
        data: dict[str, object],
        round_id: int | None = None,
        node_id: str | None = None,
        message: str | None = None,
    ) -> None:
        if self._trace is None:
            return
        self._trace.emit(
            TraceEvent(
                kind=kind,
                round_id=round_id,
                node_id=node_id,
                message=message,
                data=data,
                correlation_id=correlation_id,
            )
        )

    def close(self) -> None:
        if (
            self._world_snapshot_store is not None
            and self._previous_state is not None
        ):
            self._memory.snapshot_to(
                self._world_snapshot_store,
                round_id=self._previous_state.round_id,
            )
        self._memory.close()
        self._experiences.close()
        if self._io_journal is not None:
            self._io_journal.close()
        if self._trace is not None:
            self._trace.close()

    @property
    def feedback_memory(self):
        return self._feedback_memory.view()

    @property
    def world_memory(self):
        return self._memory.view()

    @property
    def strategic_memory(self):
        return self._strategic_memory.view()

    @property
    def policy_state(self) -> PolicyState:
        return self._policy_repo.current()

    @property
    def experience_store(self) -> ExperienceStore:
        return self._experiences

    @property
    def policy_repository(
        self,
    ) -> InMemoryPolicyStateRepository:
        return self._policy_repo
