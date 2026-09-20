from __future__ import annotations

from types import MappingProxyType
from dataclasses import replace

from fortress_agent.application.runtime import FortressAgentRuntime
from fortress_agent.candidates.basic import GatherCandidateGenerator, MoveCandidateGenerator, ResourceApproachCandidateGenerator
from fortress_agent.config.tuning import (
    RuntimeLearningConfig,
    merged_parameters,
    merged_thresholds,
    merged_utility_weight_multipliers,
)
from fortress_agent.domain.action import GatherAction
from fortress_agent.domain.policy_state import PolicyPatch, PolicyState
from fortress_agent.domain.reward import RewardBreakdown
from fortress_agent.game_rules.economy import resource_selection_score
from fortress_agent.learning.learners.base import LearnerRegistry
from fortress_agent.memory.economy import MiningRuntimeMemory
from fortress_agent.memory.world import WorldMemory
from fortress_agent.policy.context import PolicyContext
from fortress_agent.policy.strategy import StrategyProfile
from fortress_agent.protocol.codec import GameProtocolCodec
from fortress_agent.reward.utility import UtilityComposer


class Deadline:
    def remaining(self):
        return 10.0
    def expired(self):
        return False


def _parsed_state(*, worker=(5, 5), backpack=None, round_no=10):
    result = GameProtocolCodec().parse_state({
        "roundNo": round_no,
        "mapInfo": {
            "width": 41,
            "height": 32,
            "zones": [
                {"neutralType": "iron", "pos": {"x": 6, "y": 7}},
                {"neutralType": "copper", "pos": {"x": 20, "y": 20}},
            ],
        },
        "teamOur": {
            "type": "challenger", "teamId": "x", "teamName": "x",
            "goldNum": 0, "totalScore": 0, "playerTasks": [],
            "roles": [{
                "id": 10010, "pos": {"x": worker[0], "y": worker[1]},
                "roleType": "worker", "health": 220,
                "attackPower": 0, "attackRange": 0,
                "backPackCapability": 100, "backpack": backpack or [],
            }],
        },
        "teamEnemy": {"roles": []}, "robot": {"roles": []},
        "vendorShopList": [
            {"name": "iron", "price": 1},
            {"name": "copper", "price": 10},
        ],
        "weaponShopList": [], "errors": [],
    })
    assert result.ok
    return result.value


def _ctx(state, *, policy=None, mining=None):
    memory = WorldMemory()
    memory.resources.discover(resource_id="iron-near", resource_type="iron", x=6, y=7, amount=10, round_id=state.round_id)
    memory.resources.discover(resource_id="copper-far", resource_type="copper", x=20, y=20, amount=10, round_id=state.round_id)
    return PolicyContext(
        state=state,
        world_memory=memory.view(),
        policy_state=policy or PolicyState.create(
            thresholds=merged_thresholds(),
            parameters=merged_parameters(),
            utility_weights=merged_utility_weight_multipliers(),
        ),
        deadline=Deadline(),
        features=MappingProxyType({}),
        mining_memory=(mining.view() if mining is not None else None),
    )


def test_resource_formula_prefers_near_by_default_but_weights_are_configurable():
    state = _parsed_state()
    ctx = _ctx(state)
    actor = state.characters[0]
    near = ctx.world_memory.resource("iron-near")
    far = ctx.world_memory.resource("copper-far")
    near_score, _, _ = resource_selection_score(ctx, actor, near, distance=2)
    far_score, _, _ = resource_selection_score(ctx, actor, far, distance=15)
    assert near_score > far_score

    policy = PolicyState.create(
        thresholds=merged_thresholds(),
        parameters=merged_parameters({
            "resource_distance_weight": 1.0,
            "resource_market_value_weight": 1.0,
        }),
        utility_weights=merged_utility_weight_multipliers(),
    )
    value_ctx = _ctx(state, policy=policy)
    near2 = value_ctx.world_memory.resource("iron-near")
    far2 = value_ctx.world_memory.resource("copper-far")
    assert resource_selection_score(value_ctx, actor, far2, distance=15)[0] > resource_selection_score(value_ctx, actor, near2, distance=2)[0]


def test_early_day_ignores_high_watermark_but_midday_stops_new_mining_trip():
    backpack = ["iron"] * 90
    base = _parsed_state(worker=(5, 5), backpack=backpack)
    early = replace(base, phase="day", phase_round=10, turns_until_phase_change=60)
    midday = replace(base, phase="day", phase_round=40, turns_until_phase_change=30)
    strategy = StrategyProfile(strategy_id="economy", candidate_tags=frozenset({"gather"}))
    assert ResourceApproachCandidateGenerator().generate(_ctx(early), strategy)
    assert ResourceApproachCandidateGenerator().generate(_ctx(midday), strategy) == ()


def test_emergency_window_allows_one_last_collect_then_move_away():
    # Worker 位于 iron(6,7) 的相邻格。
    base = _parsed_state(worker=(6, 6))
    emergency = replace(base, phase="day", phase_round=62, turns_until_phase_change=8)
    mining = MiningRuntimeMemory()
    ctx = _ctx(emergency, mining=mining)
    strategy = StrategyProfile(strategy_id="prepare", candidate_tags=frozenset({"gather", "move"}))

    gathers = GatherCandidateGenerator().generate(ctx, strategy)
    assert len(gathers) == 1
    action = gathers[0]
    mining.record_confirmed_action(state=emergency, action=action, emergency_rounds=8)

    ctx_after = _ctx(emergency, mining=mining)
    assert GatherCandidateGenerator().generate(ctx_after, strategy) == ()
    # 紧急额外采集机会已经用掉后，普通 MOVE 不再被“采完当前矿”规则抑制。
    assert MoveCandidateGenerator().generate(ctx_after, strategy)


class _FakePrepareLearner:
    learner_id = "fake_prepare"
    def observe(self, exp, outcome):
        return None
    def propose(self, current):
        old = float(current.thresholds["prepare_margin_rounds"])
        return PolicyPatch(
            patch_id=f"fake:{current.version}",
            parent_version=current.version,
            component="thresholds",
            key="prepare_margin_rounds",
            old_value=old,
            new_value=old - 10.0,
            reason="test small-step clamp",
            proposer=self.learner_id,
            confidence=0.9,
        )


def test_runtime_learning_round_is_configurable_and_update_is_small_step():
    registry = LearnerRegistry()
    registry.register(_FakePrepareLearner())
    runtime = FortressAgentRuntime(
        policy_state=PolicyState.create(
            thresholds=merged_thresholds({"prepare_margin_rounds": 20.0}),
            parameters=merged_parameters(),
            utility_weights=merged_utility_weight_multipliers(),
        ),
        learner_registry=registry,
        runtime_learning_config=RuntimeLearningConfig(
            enabled=True,
            first_update_round=5,
            update_interval_rounds=10,
            max_patches_per_update=1,
            min_confidence=0.5,
            max_relative_change=0.10,
            max_absolute_change=1.0,
        ),
    )
    runtime._maybe_apply_runtime_learning(round_id=4, correlation_id="r4")
    assert runtime.policy_state.version == 1
    runtime._maybe_apply_runtime_learning(round_id=5, correlation_id="r5")
    assert runtime.policy_state.version == 2
    # learner 想从 20 直接改到 10，但单次绝对上限是 1，所以只能到 19。
    assert runtime.policy_state.thresholds["prepare_margin_rounds"] == 19.0
    # Base=20、Effective=19，因此 Learned Overlay 应保存 -5%，而不是绝对 -1。
    assert round(runtime.policy_state.overlay_ratio("thresholds", "prepare_margin_rounds"), 6) == -0.05
    update = runtime._round_policy_updates[-1]
    assert update["next_update_round"] == 15
    assert update["base_value"] == 20.0
    assert round(update["new_overlay_ratio"], 6) == -0.05
    assert round(update["overlay_value"], 6) == -1.0


def test_utility_formula_exposes_raw_components_and_effective_weights():
    state = _parsed_state()
    policy = PolicyState.create(
        thresholds=merged_thresholds(),
        parameters=merged_parameters(),
        utility_weights=merged_utility_weight_multipliers({"economy": 1.10}),
    )
    ctx = _ctx(state, policy=policy)
    strategy = StrategyProfile(
        strategy_id="economy",
        candidate_tags=frozenset(),
        utility_weight_overrides=MappingProxyType({"economy": 1.60}),
    )
    utility = UtilityComposer().compose(
        ctx,
        strategy,
        RewardBreakdown(economy=2.0, action_cost=0.5, total=1.5),
    )
    assert round(utility.effective_weights["economy"], 3) == 1.760
    assert utility.raw_components["economy"] == 2.0
    assert "economy*w_econ" in utility.formula
