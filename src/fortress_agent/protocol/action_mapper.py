from __future__ import annotations

from dataclasses import dataclass

from fortress_agent.domain.action import (
    AcceptTaskAction,
    AttackAction,
    BuildAction,
    BuyAction,
    DropAction,
    ExploreAction,
    GatherAction,
    MoveAction,
    RemoveAction,
    SellAction,
    SubmitAnswerAction,
    SummonTreasureAction,
    UseAction,
)
from fortress_agent.domain.decision import Decision
from fortress_agent.domain.team import TeamDecision
from fortress_agent.game_rules.build_area import BuildAreaPolicy

from .codec import GameProtocolCodec
from .final_validator import FinalResponseValidator
from .result import CodecResult
from .safe_outbound import SafeServerResponseBuilder
from .server_factory import ServerCommandFactory
from .server_outbound import ServerCommandResponse




@dataclass(frozen=True, slots=True)
class TeamEncodeResult:
    ok: bool
    json: str | None
    accepted_role_ids: tuple[str, ...] = ()
    rejected_role_ids: tuple[str, ...] = ()
    suppressed_prompt: bool = False
    suppressed_execute_cmd: bool = False
    error_code: str | None = None
    message: str | None = None


class DomainActionMapper:
    def to_wire_command(
        self,
        action,
        *,
        world_memory=None,
    ):
        if isinstance(
            action,
            (MoveAction, ExploreAction),
        ):
            return ServerCommandFactory.move(
                (action.x, action.y)
            )

        if isinstance(action, GatherAction):
            if world_memory is None:
                raise ValueError(
                    "GatherAction requires WorldMemory "
                    "to resolve resource position"
                )

            resource = world_memory.resource(
                action.resource_id
            )
            if resource is None:
                raise ValueError(
                    f"unknown resource: {action.resource_id}"
                )
            return ServerCommandFactory.collect(
                (resource.x, resource.y)
            )

        if isinstance(action, AttackAction):
            return ServerCommandFactory.attack(
                controller_id=action.controller_id,
                points=tuple(
                    (target.x, target.y)
                    for target in action.targets
                ),
            )

        if isinstance(action, SellAction):
            return ServerCommandFactory.sell(
                action.name,
                action.num,
            )

        if isinstance(action, BuyAction):
            return ServerCommandFactory.buy(
                action.name,
                action.num,
            )

        if isinstance(action, BuildAction):
            return ServerCommandFactory.build(
                action.name,
                (action.target.x, action.target.y),
            )

        if isinstance(action, RemoveAction):
            return ServerCommandFactory.remove(
                (action.target.x, action.target.y)
            )

        if isinstance(action, AcceptTaskAction):
            return ServerCommandFactory.accept_task()

        if isinstance(action, SubmitAnswerAction):
            return ServerCommandFactory.submit_answer(
                action.task_answer
            )

        if isinstance(action, SummonTreasureAction):
            return ServerCommandFactory.summon_treasure(
                points=((action.target.x, action.target.y),),
                items=action.items,
            )

        if isinstance(action, UseAction):
            return ServerCommandFactory.use(
                action.name,
                points=(
                    ()
                    if action.target is None
                    else (
                        (
                            action.target.x,
                            action.target.y,
                        ),
                    )
                ),
            )

        if isinstance(action, DropAction):
            return ServerCommandFactory.drop(
                action.name
            )

        raise TypeError(
            f"unsupported domain action: "
            f"{type(action).__name__}"
        )


class DecisionResponseEncoder:
    def __init__(
        self,
        codec: GameProtocolCodec | None = None,
        mapper: DomainActionMapper | None = None,
        safe_builder: SafeServerResponseBuilder | None = None,
        final_validator: FinalResponseValidator | None = None,
        build_area_policy: BuildAreaPolicy | None = None,
    ) -> None:
        self._codec = codec or GameProtocolCodec()
        self._mapper = mapper or DomainActionMapper()
        self._safe_builder = (
            safe_builder
            or SafeServerResponseBuilder()
        )
        self._final_validator = (
            final_validator
            or FinalResponseValidator(build_area_policy=build_area_policy)
        )

    def encode(
        self,
        decision: Decision,
        *,
        state=None,
        world_memory=None,
        feedback_memory=None,
        prompt: str | None = "",
        execute_cmd: str | None = "",
        llm_call_allowed: bool = True,
    ) -> CodecResult[str]:
        # Isolated mapper/codec tests may intentionally omit GameState.
        # In that case we still map the domain action and enforce the closed
        # Pydantic wire schema, but skip state-aware FinalResponseValidator.
        if state is None:
            try:
                command = self._mapper.to_wire_command(
                    decision.action,
                    world_memory=world_memory,
                )
            except (TypeError, ValueError) as exc:
                return CodecResult.failure(
                    error_code="domain_action_mapping_error",
                    message=str(exc),
                )

            built = self._safe_builder.build(
                {str(decision.action.actor_id): command},
                prompt=prompt,
                execute_cmd=execute_cmd,
            )
            return self._codec.serialize_server_response(
                built.response
            )

        team = TeamDecision(
            decisions=(decision,),
            prompt=prompt or "",
            execute_cmd=execute_cmd or "",
        )
        return self.encode_team(
            team,
            state=state,
            world_memory=world_memory,
            feedback_memory=feedback_memory,
            llm_call_allowed=llm_call_allowed,
        )

    def encode_team_detailed(
        self,
        team_decision: TeamDecision,
        *,
        state,
        world_memory=None,
        feedback_memory=None,
        llm_call_allowed: bool = True,
    ) -> TeamEncodeResult:
        if state is None:
            return TeamEncodeResult(
                ok=False,
                json=None,
                error_code="missing_state_for_final_validation",
                message=(
                    "real server team encoding requires current GameState"
                ),
            )

        raw_commands = {}
        mapping_rejected = []

        for decision in team_decision.decisions:
            role_id = str(decision.action.actor_id)

            try:
                raw_commands[role_id] = (
                    self._mapper.to_wire_command(
                        decision.action,
                        world_memory=world_memory,
                    )
                )
            except (TypeError, ValueError):
                mapping_rejected.append(role_id)

        built = self._safe_builder.build(
            raw_commands,
            prompt=team_decision.resolved_prompt(),
            execute_cmd=team_decision.resolved_execute_cmd(),
            state=state,
        )

        final = self._final_validator.validate(
            state=state,
            response=built.response,
            llm_call_allowed=llm_call_allowed,
            world_memory=world_memory,
            feedback_memory=feedback_memory,
        )

        suppress_prompt = any(
            issue.code == "llm_budget_exhausted"
            for issue in final.top_level_issues
        )
        suppress_execute = any(
            issue.code == "execute_cmd_outside_task"
            for issue in final.top_level_issues
        )

        response = ServerCommandResponse(
            roleCommandMap=final.valid_commands,
            prompt=(
                ""
                if suppress_prompt
                else built.response.prompt
            ),
            executeCmd=(
                ""
                if suppress_execute
                else built.response.executeCmd
            ),
        )

        encoded = self._codec.serialize_server_response(
            response
        )

        if not encoded.ok:
            return TeamEncodeResult(
                ok=False,
                json=None,
                error_code=encoded.error_code,
                message=encoded.message,
            )

        rejected = tuple(
            dict.fromkeys(
                mapping_rejected
                + list(built.omitted_roles)
                + list(final.rejected_roles)
            )
        )

        return TeamEncodeResult(
            ok=True,
            json=encoded.value,
            accepted_role_ids=tuple(
                final.valid_commands.keys()
            ),
            rejected_role_ids=rejected,
            suppressed_prompt=suppress_prompt,
            suppressed_execute_cmd=suppress_execute,
        )

    def encode_team(
        self,
        team_decision: TeamDecision,
        *,
        state,
        world_memory=None,
        feedback_memory=None,
        llm_call_allowed: bool = True,
    ) -> CodecResult[str]:
        detailed = self.encode_team_detailed(
            team_decision,
            state=state,
            world_memory=world_memory,
            feedback_memory=feedback_memory,
            llm_call_allowed=llm_call_allowed,
        )

        if not detailed.ok:
            return CodecResult.failure(
                error_code=(
                    detailed.error_code
                    or "team_encode_error"
                ),
                message=(
                    detailed.message
                    or "failed to encode team decision"
                ),
            )

        return CodecResult.success(
            detailed.json or ""
        )

    def encode_role_commands(
        self,
        role_commands,
        *,
        state=None,
        world_memory=None,
        feedback_memory=None,
        prompt: str | None = "",
        execute_cmd: str | None = "",
        llm_call_allowed: bool = True,
    ) -> CodecResult[str]:
        built = self._safe_builder.build(
            role_commands,
            prompt=prompt,
            execute_cmd=execute_cmd,
            state=state,
        )

        if state is None:
            return self._codec.serialize_server_response(
                built.response
            )

        if state is None:
            # Useful for isolated mapper/codec contract tests. Production
            # FortressAgentRuntime always supplies current GameState and thus
            # always executes FinalResponseValidator.
            return self._codec.serialize_server_response(
                built.response
            )

        final = self._final_validator.validate(
            state=state,
            response=built.response,
            llm_call_allowed=llm_call_allowed,
            world_memory=world_memory,
            feedback_memory=feedback_memory,
        )

        response = ServerCommandResponse(
            roleCommandMap=final.valid_commands,
            prompt=(
                ""
                if any(
                    issue.code == "llm_budget_exhausted"
                    for issue in final.top_level_issues
                )
                else built.response.prompt
            ),
            executeCmd=(
                ""
                if any(
                    issue.code == "execute_cmd_outside_task"
                    for issue in final.top_level_issues
                )
                else built.response.executeCmd
            ),
        )

        return self._codec.serialize_server_response(
            response
        )
