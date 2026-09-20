from __future__ import annotations

from fortress_agent.domain.decision import Decision
from fortress_agent.domain.reward import RewardBreakdown
from fortress_agent.policy.context import PolicyContext

from .record import CreditLink, ExperienceRecord, OutcomeRecord


class ExperienceBuilder:
    """Build immutable decision/outcome records.

    First implementation uses one-turn direct credit assignment:
    the reward observed on round t is assigned to the decision made on t-1.
    Longer-horizon credit can later add additional CreditLinks without
    changing ExperienceRecord.
    """

    FEATURE_SCHEMA_VERSION = 1

    def build_decision(
        self,
        *,
        ctx: PolicyContext,
        decision: Decision,
        action_probability: float = 1.0,
    ) -> ExperienceRecord:
        if not (0.0 < action_probability <= 1.0):
            raise ValueError(
                "action_probability must be in (0, 1]"
            )

        feature_vector = tuple(
            sorted(
                (
                    key,
                    self._scalar(value),
                )
                for key, value in ctx.features.items()
            )
        )

        turn_prefix = (
            ctx.correlation_id
            or f"r{ctx.state.round_id}"
        )
        decision_id = (
            f"{turn_prefix}:"
            f"p{ctx.policy_state.version}:"
            f"{decision.strategy_id}:"
            f"{decision.action.actor_id}:"
            f"{decision.action.action_type}"
        )

        return ExperienceRecord(
            experience_id=f"exp:{decision_id}",
            decision_id=decision_id,
            round_id=ctx.state.round_id,
            day=ctx.state.day,
            phase=ctx.state.phase,
            policy_version=ctx.policy_state.version,
            strategy_id=decision.strategy_id,
            feature_schema_version=self.FEATURE_SCHEMA_VERSION,
            feature_vector=feature_vector,
            action=decision.action,
            action_probability=action_probability,
            predicted_utility=decision.utility,
            latency_ms=decision.latency_ms,
            deadline_remaining_ms=ctx.deadline.remaining() * 1000.0,
            correlation_id=ctx.correlation_id,
        )

    def build_outcome(
        self,
        *,
        previous: ExperienceRecord,
        reward: RewardBreakdown,
        end_round: int,
        confidence: float = 1.0,
        action_legal: bool | None = None,
        server_error_codes: tuple[int, ...] = (),
        server_error_messages: tuple[str, ...] = (),
        command_error_signatures: tuple[str, ...] = (),
        terrain_rule_signatures: tuple[str, ...] = (),
        action_failure_signatures: tuple[str, ...] = (),
        summon_treasure_result: int | None = None,
        execute_cmd_result: str = "",
        correlation_id: str | None = None,
    ) -> tuple[OutcomeRecord, CreditLink]:
        outcome_id = (
            f"outcome:{previous.decision_id}:"
            f"{end_round}"
        )

        outcome = OutcomeRecord(
            outcome_id=outcome_id,
            start_round=previous.round_id,
            end_round=end_round,
            reward=reward,
            confidence=confidence,
            action_legal=action_legal,
            server_error_codes=server_error_codes,
            server_error_messages=server_error_messages,
            command_error_signatures=command_error_signatures,
            terrain_rule_signatures=terrain_rule_signatures,
            action_failure_signatures=action_failure_signatures,
            summon_treasure_result=summon_treasure_result,
            execute_cmd_result=execute_cmd_result,
            correlation_id=correlation_id,
        )

        credit = CreditLink(
            outcome_id=outcome_id,
            decision_id=previous.decision_id,
            weight=1.0,
        )

        return outcome, credit

    @staticmethod
    def _scalar(value):
        if value is None:
            return None
        if isinstance(value, (bool, int, float, str)):
            return value
        # Avoid serializing arbitrary model objects into the compact
        # feature vector.
        return str(value)
