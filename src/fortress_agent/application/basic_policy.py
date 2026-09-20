from __future__ import annotations

from dataclasses import dataclass

from fortress_agent.candidates.base import CandidateRegistry
from fortress_agent.candidates.basic import (
    AttackCandidateGenerator,
    ExplorationCandidateGenerator,
    GatherCandidateGenerator,
    MoveCandidateGenerator,
    ResourceApproachCandidateGenerator,
    NightResourceApproachCandidateGenerator,
    NightWorkerRetreatCandidateGenerator,
)
from fortress_agent.candidates.navigation import (
    TaskApproachCandidateGenerator,
    VendorApproachCandidateGenerator,
    WeaponShopApproachCandidateGenerator,
    UseTargetApproachCandidateGenerator,
    BaseReturnCandidateGenerator,
    DefensePostCandidateGenerator,
    WallBuildApproachCandidateGenerator,
    WeaponBuildApproachCandidateGenerator,
)
from fortress_agent.candidates.business import (
    AcceptTaskCandidateGenerator,
    BuildCandidateGenerator,
    BuyCandidateGenerator,
    RemoveCandidateGenerator,
    SellCandidateGenerator,
    SubmitAnswerCandidateGenerator,
    SummonTreasureCandidateGenerator,
    UseCandidateGenerator,
)
from fortress_agent.domain.policy_state import PolicyState
from fortress_agent.domain.state import GameState
from fortress_agent.evaluators.base import EvaluatorRegistry
from fortress_agent.evaluators.basic import (
    AttackEvaluator,
    ExplorationEvaluator,
    GatherEvaluator,
    MoveEvaluator,
    ResourceApproachEvaluator,
)
from fortress_agent.evaluators.navigation import GoalApproachEvaluator
from fortress_agent.evaluators.business import (
    AcceptTaskEvaluator,
    BuildEvaluator,
    BuyEvaluator,
    RemoveEvaluator,
    SellEvaluator,
    SubmitAnswerEvaluator,
    TreasureEvaluator,
    UseEvaluator,
)
from fortress_agent.features.base import FeatureRegistry
from fortress_agent.features.basic import BasicWorldFeatureExtractor
from fortress_agent.features.threat import ThreatFeatureExtractor
from fortress_agent.memory.world import WorldMemoryView
from fortress_agent.observability.trace import TraceSink
from fortress_agent.policy.context_factory import PolicyContextFactory
from fortress_agent.policy.build_catalog import BuildCatalog
from fortress_agent.game_rules.build_area import BuildAreaPolicy, DEFAULT_BUILD_AREA_POLICY
from fortress_agent.policy.decision_builder import BasicDecisionBuilder
from fortress_agent.policy.graph.engine import PolicyGraphEngine
from fortress_agent.policy.graph.reference import (
    ReferencePolicyServices,
    build_reference_policy_graph,
)
from fortress_agent.policy.legal import BasicLegalActionFilter
from fortress_agent.policy.ranker import RewardAwareRanker
from fortress_agent.policy.services import CandidateService
from fortress_agent.policy.validator import BasicValidationService
from fortress_agent.policy.team import TeamPlanner
from fortress_agent.protocol.action_mapper import DecisionResponseEncoder
from fortress_agent.reward.engine import RewardModelRegistry
from fortress_agent.reward.models import (
    AttackRewardModel,
    ExplorationRewardModel,
    GatherRewardModel,
    MoveRewardModel,
    ResourceApproachRewardModel,
)
from fortress_agent.reward.navigation import GoalApproachRewardModel
from fortress_agent.reward.business import (
    AcceptTaskRewardModel,
    BuildRewardModel,
    BuyRewardModel,
    RemoveRewardModel,
    SellRewardModel,
    SubmitAnswerRewardModel,
    TreasureRewardModel,
    UseRewardModel,
)
from fortress_agent.reward.utility import UtilityComposer
from fortress_agent.rules.base import BasicRuleEngine, RuleRegistry
from fortress_agent.rules.basic import (
    GatherOnlyDuringDayRule,
    GatherWorkerOnlyRule,
)
from fortress_agent.safety.deadline import DeadlineView
from fortress_agent.safety.emergency import BasicEmergencyPolicy
from fortress_agent.safety.runtime_guard import BasicRuntimeModeResolver
from fortress_agent.strategies.reference import build_reference_strategy_selector


@dataclass(slots=True)
class BasicPolicyRuntime:
    context_factory: PolicyContextFactory
    graph_engine: PolicyGraphEngine
    encoder: DecisionResponseEncoder
    team_planner: TeamPlanner | None = None

    async def decide(
        self,
        *,
        state: GameState,
        world_memory: WorldMemoryView,
        policy_state: PolicyState,
        deadline: DeadlineView,
        strategic_memory=None,
        feedback_memory=None,
    ):
        ctx = self.context_factory.build(
            state=state,
            world_memory=world_memory,
            policy_state=policy_state,
            deadline=deadline,
            strategic_memory=strategic_memory,
            feedback_memory=feedback_memory,
        )

        frame = await self.graph_engine.run(ctx)

        if frame.decision is None:
            raise RuntimeError("policy graph ended without decision")

        return frame.decision


    def decide_team(
        self,
        *,
        state: GameState,
        world_memory: WorldMemoryView,
        policy_state: PolicyState,
        deadline: DeadlineView,
        strategic_memory=None,
        feedback_memory=None,
        prompt: str = "",
        execute_cmd: str = "",
        strategy=None,
    ):
        if self.team_planner is None:
            raise RuntimeError("team planner is not configured")

        ctx = self.context_factory.build(
            state=state,
            world_memory=world_memory,
            policy_state=policy_state,
            deadline=deadline,
            strategic_memory=strategic_memory,
            feedback_memory=feedback_memory,
        )

        return self.team_planner.plan(
            ctx,
            prompt=prompt,
            execute_cmd=execute_cmd,
            strategy=strategy,
        )

    async def decide_json(
        self,
        *,
        state: GameState,
        world_memory: WorldMemoryView,
        policy_state: PolicyState,
        deadline: DeadlineView,
        strategic_memory=None,
    ):
        decision = await self.decide(
            state=state,
            world_memory=world_memory,
            policy_state=policy_state,
            deadline=deadline,
            strategic_memory=strategic_memory,
        )
        return self.encoder.encode(
            decision,
            state=state,
            world_memory=world_memory,
        )


def build_basic_policy_runtime(
    *,
    trace_sink: TraceSink | None = None,
    build_catalog: BuildCatalog | None = None,
    build_area_policy: BuildAreaPolicy | None = None,
) -> BasicPolicyRuntime:
    """组装默认生产 Policy 的 Composition Root。

    所有 Feature/Candidate/Reward/Evaluator/Rule/Strategy/TeamPlanner 都在这里注册。
    新增插件后如果没有在这里注册，它不会进入生产决策链。此函数只负责依赖装配，
    具体规则实现应留在各自模块，避免把业务 if/else 堆回 Composition Root。
    """

    features = FeatureRegistry()
    features.register(BasicWorldFeatureExtractor())
    features.register(ThreatFeatureExtractor())

    build_catalog = build_catalog or BuildCatalog.official_default()
    build_area_policy = build_area_policy or DEFAULT_BUILD_AREA_POLICY

    reward_models = RewardModelRegistry()
    reward_models.register(MoveRewardModel())
    reward_models.register(ResourceApproachRewardModel())
    reward_models.register(GoalApproachRewardModel())
    reward_models.register(AttackRewardModel())
    reward_models.register(ExplorationRewardModel())
    reward_models.register(GatherRewardModel())
    reward_models.register(SellRewardModel())
    reward_models.register(RemoveRewardModel())
    reward_models.register(BuyRewardModel())
    reward_models.register(UseRewardModel())
    reward_models.register(AcceptTaskRewardModel())
    reward_models.register(SubmitAnswerRewardModel())
    reward_models.register(TreasureRewardModel())
    reward_models.register(
        BuildRewardModel(build_catalog)
    )

    composer = UtilityComposer()

    evaluators = EvaluatorRegistry()
    evaluators.register(
        MoveEvaluator(reward_models, composer)
    )
    evaluators.register(
        ResourceApproachEvaluator(reward_models, composer)
    )
    evaluators.register(
        GoalApproachEvaluator(reward_models, composer)
    )
    evaluators.register(
        AttackEvaluator(reward_models, composer)
    )
    evaluators.register(
        ExplorationEvaluator(reward_models, composer)
    )
    evaluators.register(
        GatherEvaluator(reward_models, composer)
    )
    evaluators.register(
        SellEvaluator(reward_models, composer)
    )
    evaluators.register(
        RemoveEvaluator(reward_models, composer)
    )
    evaluators.register(
        BuyEvaluator(reward_models, composer)
    )
    evaluators.register(
        UseEvaluator(reward_models, composer)
    )
    evaluators.register(
        AcceptTaskEvaluator(
            reward_models,
            composer,
        )
    )
    evaluators.register(
        SubmitAnswerEvaluator(
            reward_models,
            composer,
        )
    )
    evaluators.register(
        TreasureEvaluator(
            reward_models,
            composer,
        )
    )
    evaluators.register(
        BuildEvaluator(
            reward_models,
            composer,
        )
    )

    candidates = CandidateRegistry()
    candidates.register(MoveCandidateGenerator())
    candidates.register(ResourceApproachCandidateGenerator())
    candidates.register(NightResourceApproachCandidateGenerator())
    candidates.register(NightWorkerRetreatCandidateGenerator())
    candidates.register(TaskApproachCandidateGenerator())
    candidates.register(VendorApproachCandidateGenerator())
    candidates.register(WeaponShopApproachCandidateGenerator())
    candidates.register(UseTargetApproachCandidateGenerator())
    candidates.register(BaseReturnCandidateGenerator())
    candidates.register(DefensePostCandidateGenerator())
    candidates.register(WallBuildApproachCandidateGenerator())
    candidates.register(WeaponBuildApproachCandidateGenerator())
    candidates.register(AttackCandidateGenerator())
    candidates.register(ExplorationCandidateGenerator())
    candidates.register(GatherCandidateGenerator())
    candidates.register(SellCandidateGenerator())
    candidates.register(RemoveCandidateGenerator())
    candidates.register(BuyCandidateGenerator())
    candidates.register(UseCandidateGenerator())
    candidates.register(
        AcceptTaskCandidateGenerator()
    )
    candidates.register(
        SubmitAnswerCandidateGenerator()
    )
    candidates.register(
        SummonTreasureCandidateGenerator()
    )
    candidates.register(
        BuildCandidateGenerator(build_catalog, build_area_policy)
    )

    rules = RuleRegistry()
    rules.register(GatherOnlyDuringDayRule())
    rules.register(GatherWorkerOnlyRule())

    legal_filter = BasicLegalActionFilter(build_area_policy=build_area_policy)

    strategy_selector = build_reference_strategy_selector()
    candidate_service = CandidateService(candidates)
    rule_engine = BasicRuleEngine(rules)
    ranker = RewardAwareRanker(evaluators)

    services = ReferencePolicyServices(
        runtime=BasicRuntimeModeResolver(),
        strategy=strategy_selector,
        candidates=candidate_service,
        legal=legal_filter,
        rules=rule_engine,
        ranker=ranker,
        validator=BasicValidationService(legal_filter),
        emergency=BasicEmergencyPolicy(),
        decision=BasicDecisionBuilder(),
    )

    graph = build_reference_policy_graph(services)

    team_planner = TeamPlanner(
        strategy_selector=strategy_selector,
        candidate_service=candidate_service,
        legal_filter=legal_filter,
        rule_engine=rule_engine,
        ranker=ranker,
    )

    return BasicPolicyRuntime(
        context_factory=PolicyContextFactory(features),
        graph_engine=PolicyGraphEngine(
            graph,
            trace_sink=trace_sink,
        ),
        encoder=DecisionResponseEncoder(build_area_policy=build_area_policy),
        team_planner=team_planner,
    )
