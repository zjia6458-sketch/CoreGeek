from __future__ import annotations

from fortress_agent.domain.decision import Decision


class BasicDecisionBuilder:
    def build(self, ctx, frame):
        if frame.selected_action is None:
            raise ValueError("selected_action is required")
        if frame.selected_utility is None:
            raise ValueError("selected_utility is required")

        strategy_id = (
            getattr(frame.strategy, "strategy_id", None)
            or "emergency"
        )

        return Decision(
            action=frame.selected_action,
            strategy_id=strategy_id,
            utility=frame.selected_utility,
            matched_rules=frame.matched_rules,
            rejected_reasons=frame.rejected_reasons,
            policy_version=ctx.policy_state.version,
        )
