from __future__ import annotations

from dataclasses import replace
from types import MappingProxyType

from fortress_agent.config.tuning import DEFAULT_STRATEGY_PARAMETERS, DEFAULT_THRESHOLDS
from fortress_agent.policy.context import PolicyContext
from fortress_agent.policy.strategy import (
    StrategyObjective,
    StrategyProfile,
)

from .graph import (
    StrategyActivation,
    StrategyActivator,
    StrategyActivatorRegistry,
    StrategyGraphBuilder,
    StrategyGraphRegistry,
    StrategyNode,
    StrategyNodeResult,
)


class FixedProfileNode(StrategyNode):
    def __init__(
        self,
        node_id: str,
        profile: StrategyProfile,
    ) -> None:
        self.node_id = node_id
        self._profile = profile

    def run(self, ctx, session):
        # StrategyProfile 中的基准权重属于软策略参数。V0.5.6 起不再把这些
        # 数字锁死在 StrategyGraph 源码里，而是按 strategy_id 从 PolicyState
        # parameters 读取。这样 main3.py 修改配置后无需改图拓扑。
        prefix = f"strategy_{self._profile.strategy_id}_"
        weights = dict(self._profile.utility_weight_overrides)
        for component, original in tuple(weights.items()):
            key = f"{prefix}weight_{component}"
            weights[component] = float(ctx.policy_state.parameters.get(key, original))

        risk = float(
            ctx.policy_state.parameters.get(
                f"{prefix}risk_multiplier",
                self._profile.risk_multiplier,
            )
        )
        metadata = dict(self._profile.metadata)
        if "minimum_action_utility" in metadata:
            metadata["minimum_action_utility"] = float(
                ctx.policy_state.parameters.get(
                    f"{prefix}minimum_action_utility",
                    metadata["minimum_action_utility"],
                )
            )

        objectives = tuple(
            replace(
                objective,
                priority=float(
                    ctx.policy_state.parameters.get(
                        f"{prefix}objective_{objective.objective_id}_priority",
                        objective.priority,
                    )
                ),
            )
            for objective in self._profile.objectives
        )
        profile = replace(
            self._profile,
            utility_weight_overrides=MappingProxyType(weights),
            risk_multiplier=risk,
            objectives=objectives,
            metadata=MappingProxyType(metadata),
        )
        return StrategyNodeResult(outcome="done", profile=profile)


class LongHorizonDecisionNode(StrategyNode):
    """A reusable example of a multi-branch complex strategy node."""

    node_id = "long_horizon_decision"

    def __init__(self) -> None:
        # 阈值在 run() 时从 PolicyState 读取，允许生产配置覆盖。
        pass

    def run(
        self,
        ctx: PolicyContext,
        session,
    ) -> StrategyNodeResult:
        advisory = (
            ctx.strategic_memory.active_advisory(
                ctx.state.round_id
            )
            if ctx.strategic_memory is not None
            else None
        )

        if (
            advisory is not None
            and advisory.effective_strength
            >= float(ctx.policy_state.parameters.get(
                "strategy_llm_advisory_threshold",
                DEFAULT_STRATEGY_PARAMETERS["strategy_llm_advisory_threshold"],
            ))
        ):
            mode = advisory.recommended_mode

            if mode == "task":
                return StrategyNodeResult(
                    outcome="task_bias"
                )

            if mode == "conservative":
                return StrategyNodeResult(
                    outcome="conservative"
                )

            if mode == "explore":
                return StrategyNodeResult(
                    outcome="llm_explore"
                )

        if self._has_resource_opportunity(ctx):
            return StrategyNodeResult(
                outcome="economy"
            )

        return StrategyNodeResult(
            outcome="explore"
        )

    @staticmethod
    def _has_resource_opportunity(
        ctx: PolicyContext,
    ) -> bool:
        available = ctx.world_memory.available_resources()

        for actor in ctx.state.characters:
            if actor.role != "worker":
                continue

            for resource in available:
                # Resources are globally listed by mapInfo and are hard
                # obstacles. Economy mode is appropriate when there is a
                # resource to approach or collect.
                if resource.status.value == "available":
                    return True

        return False


class NightActivator(StrategyActivator):
    activator_id = "night"

    def activate(self, ctx):
        if ctx.state.phase != "night":
            return None
        return StrategyActivation(
            graph_id="defense",
            score=float(ctx.policy_state.parameters.get("strategy_night_activation_score", DEFAULT_STRATEGY_PARAMETERS["strategy_night_activation_score"])),
            priority=int(ctx.policy_state.parameters.get("strategy_night_activation_priority", DEFAULT_STRATEGY_PARAMETERS["strategy_night_activation_priority"])),
            reason="night hard safety priority",
        )


class PrepareActivator(StrategyActivator):
    activator_id = "prepare"

    def activate(self, ctx):
        if ctx.state.phase != "day":
            return None

        turns = ctx.state.turns_until_phase_change
        margin = int(
            ctx.policy_state.thresholds.get(
                "prepare_margin_rounds",
                ctx.policy_state.thresholds.get("prepare_margin", DEFAULT_THRESHOLDS["prepare_margin_rounds"]),
            )
        )

        if turns is None or turns > margin:
            return None

        return StrategyActivation(
            graph_id="prepare",
            score=float(ctx.policy_state.parameters.get("strategy_prepare_activation_score", DEFAULT_STRATEGY_PARAMETERS["strategy_prepare_activation_score"])),
            priority=int(ctx.policy_state.parameters.get("strategy_prepare_activation_priority", DEFAULT_STRATEGY_PARAMETERS["strategy_prepare_activation_priority"])),
            reason="day-to-night preparation window",
        )


class ActiveTaskActivator(StrategyActivator):
    activator_id = "active_task"

    def activate(self, ctx):
        if not ctx.state.phase_task.strip():
            return None

        return StrategyActivation(
            graph_id="active_task",
            score=float(ctx.policy_state.parameters.get("strategy_active_task_activation_score", DEFAULT_STRATEGY_PARAMETERS["strategy_active_task_activation_score"])),
            priority=int(ctx.policy_state.parameters.get("strategy_active_task_activation_priority", DEFAULT_STRATEGY_PARAMETERS["strategy_active_task_activation_priority"])),
            reason="self-evolution task currently active",
        )


class DayDefaultActivator(StrategyActivator):
    activator_id = "day_default"

    def activate(self, ctx):
        if ctx.state.phase != "day":
            return None
        return StrategyActivation(
            graph_id="day_default",
            score=float(ctx.policy_state.parameters.get("strategy_day_default_activation_score", DEFAULT_STRATEGY_PARAMETERS["strategy_day_default_activation_score"])),
            priority=int(ctx.policy_state.parameters.get("strategy_day_default_activation_priority", DEFAULT_STRATEGY_PARAMETERS["strategy_day_default_activation_priority"])),
            reason="default daytime strategy graph",
        )


def _profile(
    strategy_id: str,
    tags: set[str],
    weights: dict[str, float],
    *,
    risk: float = 1.0,
    objectives=(),
    metadata=None,
):
    return StrategyProfile(
        strategy_id=strategy_id,
        candidate_tags=frozenset(tags),
        utility_weight_overrides=MappingProxyType(
            dict(weights)
        ),
        risk_multiplier=risk,
        objectives=tuple(objectives),
        metadata=MappingProxyType(
            dict(metadata or {})
        ),
    )


def build_reference_strategy_selector():
    graphs = StrategyGraphRegistry()
    activators = StrategyActivatorRegistry()

    defense = (
        StrategyGraphBuilder(
            "defense",
            "defense_profile",
        )
        .add_node(
            FixedProfileNode(
                "defense_profile",
                _profile(
                    "defense",
                    {
                        "defense",
                        "move",
                        "use",
                    },
                    {
                        "survival": 2.5,
                        "risk": 2.0,
                        "score": 1.2,
                    },
                    risk=1.5,
                    metadata={"minimum_action_utility": 0.5},
                    objectives=(
                        StrategyObjective(
                            "protect_base",
                            1.0,
                            "reduce robot threat to own base",
                        ),
                    ),
                ),
            )
        )
        .route(
            "defense_profile",
            "done",
            "__END__",
        )
        .build()
    )

    prepare = (
        StrategyGraphBuilder(
            "prepare",
            "prepare_profile",
        )
        .add_node(
            FixedProfileNode(
                "prepare_profile",
                _profile(
                    "prepare",
                    {
                        "prepare",
                        "prepare_gather",
                        "build",
                        "move",
                        "buy",
                        "sell",
                        "use",
                    },
                    {
                        "position": 1.5,
                        "survival": 1.5,
                        "information": 0.25,
                    },
                    risk=1.25,
                    metadata={"minimum_action_utility": 0.0},
                    objectives=(
                        StrategyObjective(
                            "return_and_prepare",
                            1.0,
                            "position roles for upcoming night",
                        ),
                    ),
                ),
            )
        )
        .route(
            "prepare_profile",
            "done",
            "__END__",
        )
        .build()
    )

    active_task = (
        StrategyGraphBuilder(
            "active_task",
            "task_profile",
        )
        .add_node(
            FixedProfileNode(
                "task_profile",
                _profile(
                    "active_task",
                    {
                        "task",
                        "move",
                        "use",
                        "treasure",
                        # Task 是 Pioneer 的职责，不应冻结两个 Worker。
                        "gather",
                        "sell",
                        "buy",
                        "build",
                    },
                    {
                        "task": 3.0,
                        "economy": 1.6,
                        "survival": 1.2,
                        "information": 0.5,
                        "position": 1.2,
                    },
                    objectives=(
                        StrategyObjective(
                            "complete_active_task",
                            1.0,
                            "prioritize active self-evolution task",
                        ),
                    ),
                    metadata={
                        "allow_task_llm": True,
                        "allow_sandbox": True,
                    },
                ),
            )
        )
        .route(
            "task_profile",
            "done",
            "__END__",
        )
        .build()
    )

    # This graph demonstrates multi-hop routing. Adding another decision branch
    # requires a node + transition registration, not editing the engine.
    day_builder = (
        StrategyGraphBuilder(
            "day_default",
            "long_horizon_decision",
        )
        .add_node(
            LongHorizonDecisionNode()
        )
        .add_node(
            FixedProfileNode(
                "economy_profile",
                _profile(
                    "economy",
                    {
                        "gather",
                        "sell",
                        "buy",
                        "use",
                        "move",
                        "explore",
                        "task",
                        "treasure",
                        "build",
                    },
                    {
                        "economy": 1.6,
                        "information": 0.8,
                        "position": 1.0,
                        "task": 1.8,
                    },
                    metadata={"minimum_action_utility": 0.0},
                    objectives=(
                        StrategyObjective(
                            "increase_economy",
                            0.9,
                            "convert resource opportunities into useful economy",
                        ),
                    ),
                ),
            )
        )
        .add_node(
            FixedProfileNode(
                "explore_profile",
                _profile(
                    "explore",
                    {
                        "explore",
                        "task",
                        "treasure",
                        "move",
                        "gather",
                        "sell",
                        "buy",
                        "use",
                        "build",
                    },
                    {
                        "information": 2.0,
                        "position": 1.25,
                        "task": 1.2,
                    },
                    metadata={"minimum_action_utility": 0.0},
                ),
            )
        )
        .add_node(
            FixedProfileNode(
                "llm_explore_profile",
                _profile(
                    "llm_explore",
                    {
                        "explore",
                        "task",
                        "treasure",
                        "move",
                        "gather",
                        "sell",
                        "buy",
                        "use",
                        "build",
                    },
                    {
                        "information": 2.5,
                        "position": 1.4,
                        "task": 1.2,
                    },
                    metadata={
                        "source": "validated_llm_advisory",
                    },
                ),
            )
        )
        .add_node(
            FixedProfileNode(
                "task_bias_profile",
                _profile(
                    "llm_task_search",
                    {
                        "task",
                        "explore",
                        "move",
                        "treasure",
                        "gather",
                        "sell",
                        "buy",
                        "use",
                        "build",
                    },
                    {
                        "task": 2.5,
                        "information": 1.8,
                        "position": 1.3,
                    },
                ),
            )
        )
        .add_node(
            FixedProfileNode(
                "conservative_profile",
                _profile(
                    "llm_conservative",
                    {
                        "move",
                        "gather",
                        "sell",
                        "buy",
                        "use",
                    },
                    {
                        "survival": 1.5,
                        "risk": 2.0,
                        "economy": 1.1,
                    },
                    risk=1.5,
                ),
            )
        )
        .route(
            "long_horizon_decision",
            "economy",
            "economy_profile",
        )
        .route(
            "long_horizon_decision",
            "explore",
            "explore_profile",
        )
        .route(
            "long_horizon_decision",
            "llm_explore",
            "llm_explore_profile",
        )
        .route(
            "long_horizon_decision",
            "task_bias",
            "task_bias_profile",
        )
        .route(
            "long_horizon_decision",
            "conservative",
            "conservative_profile",
        )
    )

    for node in (
        "economy_profile",
        "explore_profile",
        "llm_explore_profile",
        "task_bias_profile",
        "conservative_profile",
    ):
        day_builder.route(
            node,
            "done",
            "__END__",
        )

    graphs.register(defense)
    graphs.register(prepare)
    graphs.register(active_task)
    graphs.register(day_builder.build())

    activators.register(NightActivator())
    activators.register(PrepareActivator())
    activators.register(ActiveTaskActivator())
    activators.register(DayDefaultActivator())

    from .graph import GraphStrategySelector

    return GraphStrategySelector(
        graphs=graphs,
        activators=activators,
    )
