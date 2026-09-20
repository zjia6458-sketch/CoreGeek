from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

# ---------------------------------------------------------------------------
# 默认值仅是策略基线，不是官方游戏硬规则。
# 生产环境由 main3.py 显式传入同名配置；这里的默认值用于测试/离线工具兼容。
# ---------------------------------------------------------------------------
DEFAULT_THRESHOLDS: Mapping[str, float] = MappingProxyType({
    # 白天剩余多少回合进入 prepare；prepare 的主要目标是站位/回防，不等同于采矿紧急撤离。
    "prepare_margin_rounds": 20.0,
    # 为把 stone 真正转成围墙而预留的施工窗口。该窗口可以早于 prepare。
    "wall_build_reserve_rounds": 25.0,
    # 距离黑夜 <= 此值时进入采矿紧急阶段：已在矿旁的 Worker 最多再采 1 次，然后撤离。
    "mining_emergency_rounds": 8.0,
    # 每个白天开始后的前 N 回合属于“填满背包优先”阶段。
    "early_day_full_backpack_rounds": 30.0,
    # 一般情况下背包使用率达到该值后，不再开启新的远距离采矿行程。
    "backpack_high_watermark_ratio": 0.80,
    # 进入 wall_build_reserve 窗口后，矿物占背包达到该比例就应返场施工/变现。
    "near_night_mineral_return_ratio": 0.35,
    # 正常 stone 运输批量；避免采 1 块就往返一次。
    "stone_batch_size": 4.0,
    # 每个 Worker 每回合保留的资源目标上限，给 TeamPlanner 留次优方案但限制 A* 数量。
    "resource_candidate_limit": 2.0,
    # 夜战候选搜索宽度；只影响搜索性能，不改变武器合法性。
    "attack_target_pool_limit": 12.0,
    "attack_target_set_limit": 32.0,
    # 建造返场每回合最多检查的高优先级建造点数量。
    "build_target_lookahead": 4.0,
    # 三面墙 Blueprint 的标准目标是 16 格；只有 16/16 才结束主动建设阶段。
    "wall_day1_target": 16.0,
    "wall_target_increment_per_day": 0.0,
    "wall_target_max": 16.0,
    # 资源目标至少保持若干回合，除非目标消失、不可达或夜间安全条件失效。
    "resource_commitment_min_rounds": 4.0,
    # 夜间只考虑地图边缘带中的矿点。
    "night_edge_mining_margin_cells": 5.0,
    # 机器人预测未来多少回合。
    "night_robot_prediction_horizon": 12.0,
    # 最近真实移动方向先外推多少步，再重新向基地收缩。
    "night_robot_observed_heading_steps": 3.0,
    # 机器人攻击距离外的硬/软安全冗余。
    "night_robot_hard_safety_margin": 1.0,
    "night_robot_soft_safety_margin": 3.0,
    # Safe A* 最大步数，避免夜间远征耗尽决策预算。
    "night_safe_path_max_steps": 64.0,
    # Worker 夜间采矿最低生命比例。
    "night_worker_min_hp_ratio": 0.55,
    # 到矿以后至少还能安全驻留/采集多少回合。
    "night_resource_min_safe_hold_rounds": 3.0,
    # 角色低于 30% 生命进入治疗恢复。
    "character_medicine_hp_ratio": 0.30,
    # Day2+ 墙低于该血量比例时优先使用 WallFixer。
    "wall_fixer_hp_ratio": 0.50,
})

DEFAULT_PARAMETERS: Mapping[str, float] = MappingProxyType({
    # 资源目标评分：score = 距离权重/(distance+1) + market_value*价值权重 + bonus。
    # 默认距离明显比价格重要，从而优先就近采矿，而不是横穿地图追高价矿。
    "resource_distance_weight": 8.00,
    "resource_market_value_weight": 0.10,
    # 三面墙完成后的经济阶段：转为“价值优先、距离次要”。
    "post_wall_resource_distance_weight": 2.00,
    "post_wall_resource_market_value_weight": 1.00,
    # 当前/最近已承诺矿点的黏性奖励，减少矿点间来回切换。
    "resource_commitment_bonus": 3.00,
    # 围墙阶段对 stone 的额外偏好。
    "resource_wall_stone_bonus": 5.00,
    # 主建设者在墙体阶段的 stone 额外偏好。
    "resource_builder_stone_bonus": 1.00,
    # 三塔完成后主建设者追非 stone 的惩罚。
    "resource_builder_nonstone_penalty": 1.00,
    # 已经贴着当前矿时，对继续 collect 的额外 economy shaping；用于“尽量采完当前矿”。
    "gather_current_mine_bonus": 2.50,
    # 夜间 Safe A* / Resource 安全评分参数。hard threshold 以上直接禁止。
    "night_threat_path_weight": 6.0,
    "night_hard_risk_threshold": 1.0,
    "night_resource_max_risk": 0.35,
    "night_escape_max_risk": 0.45,
    "night_resource_safety_weight": 10.0,
    "night_resource_distance_weight": 7.0,
    "night_resource_value_weight": 0.08,
})


# StrategyGraph / StrategyProfile 的软参数。它们决定策略优先级与 Utility 基准权重，
# 不属于官方规则，因此也进入统一配置域。生产环境可由 main3.py 同名覆盖。
DEFAULT_STRATEGY_PARAMETERS: Mapping[str, float] = MappingProxyType({
    "strategy_llm_advisory_threshold": 0.45,
    "strategy_night_activation_score": 1.0,
    "strategy_night_activation_priority": 1000.0,
    "strategy_prepare_activation_score": 1.0,
    "strategy_prepare_activation_priority": 900.0,
    "strategy_active_task_activation_score": 1.0,
    "strategy_active_task_activation_priority": 850.0,
    "strategy_day_default_activation_score": 0.10,
    "strategy_day_default_activation_priority": 100.0,

    "strategy_defense_weight_survival": 2.50,
    "strategy_defense_weight_risk": 2.00,
    "strategy_defense_weight_score": 1.20,
    "strategy_defense_risk_multiplier": 1.50,
    "strategy_defense_minimum_action_utility": 0.50,

    "strategy_prepare_weight_position": 1.50,
    "strategy_prepare_weight_survival": 1.50,
    "strategy_prepare_weight_information": 0.25,
    "strategy_prepare_risk_multiplier": 1.25,
    "strategy_prepare_minimum_action_utility": 0.00,

    "strategy_active_task_weight_task": 3.00,
    "strategy_active_task_weight_economy": 1.60,
    "strategy_active_task_weight_survival": 1.20,
    "strategy_active_task_weight_information": 0.50,
    "strategy_active_task_weight_position": 1.20,

    "strategy_economy_weight_economy": 1.60,
    "strategy_economy_weight_information": 0.80,
    "strategy_economy_weight_position": 1.00,
    "strategy_economy_weight_task": 1.80,
    "strategy_economy_minimum_action_utility": 0.00,

    "strategy_explore_weight_information": 2.00,
    "strategy_explore_weight_position": 1.25,
    "strategy_explore_weight_task": 1.20,
    "strategy_explore_minimum_action_utility": 0.00,

    "strategy_llm_explore_weight_information": 2.50,
    "strategy_llm_explore_weight_position": 1.40,
    "strategy_llm_explore_weight_task": 1.20,

    "strategy_llm_task_search_weight_task": 2.50,
    "strategy_llm_task_search_weight_information": 1.80,
    "strategy_llm_task_search_weight_position": 1.30,

    "strategy_llm_conservative_weight_survival": 1.50,
    "strategy_llm_conservative_weight_risk": 2.00,
    "strategy_llm_conservative_weight_economy": 1.10,
    "strategy_llm_conservative_risk_multiplier": 1.50,

    # StrategyObjective 的 priority 同样属于软优先级，不写死在图实现里。
    "strategy_defense_objective_protect_base_priority": 1.00,
    "strategy_prepare_objective_return_and_prepare_priority": 1.00,
    "strategy_active_task_objective_complete_active_task_priority": 1.00,
    "strategy_economy_objective_increase_economy_priority": 0.90,
})

# 最终 UtilityComposer 的倍率修正。1.0 表示不改变 StrategyProfile 的基准权重。
# 在线学习只允许对此类软倍率做很小的调整。
DEFAULT_UTILITY_WEIGHT_MULTIPLIERS: Mapping[str, float] = MappingProxyType({
    "score": 1.0,
    "survival": 1.0,
    "economy": 1.0,
    "information": 1.0,
    "position": 1.0,
    "task": 1.0,
    "time_cost": 1.0,
    "risk": 1.0,
})


@dataclass(frozen=True, slots=True)
class RuntimeLearningConfig:
    """运行时轻量学习开关。

    学习器只能提出 :class:`PolicyPatch`；Runtime 仍经过候选创建、约束检查和显式
    promote。它只能修改允许列表中的软参数，不能修改协议/Legal/FinalValidator。
    """

    enabled: bool = True
    # 第一次允许自动更新的游戏回合。
    first_update_round: int = 20
    # 此后每隔多少个游戏回合尝试一次小幅更新。
    update_interval_rounds: int = 20
    # 每个更新点最多实际提升多少个 patch，默认 1，避免同一时刻多参数联动失控。
    max_patches_per_update: int = 1
    # 低于该置信度的 learner 提案不自动提升。
    min_confidence: float = 0.55
    # 单次相对变化上限。例如 0.10 表示最多改变旧值的 10%。
    max_relative_change: float = 0.10
    # 单次绝对变化上限，主要保护 prepare_margin 等以“回合”为单位的阈值。
    max_absolute_change: float = 1.0
    # PrepareMarginLearner 的最小样本数/步长/上下界与触发阈值。
    prepare_min_samples: int = 5
    prepare_step_rounds: float = 1.0
    prepare_min_rounds: float = 8.0
    prepare_max_rounds: float = 30.0
    prepare_negative_reward_threshold: float = -0.5
    prepare_positive_reward_threshold: float = 2.0
    # Economy utility multiplier 的学习设置。
    economy_min_samples: int = 5
    economy_learning_rate: float = 0.05
    economy_multiplier_min: float = 0.75
    economy_multiplier_max: float = 1.25
    economy_error_deadband: float = 0.5


def _merged(defaults: Mapping[str, float], overrides: Mapping[str, float] | None) -> Mapping[str, float]:
    data = dict(defaults)
    if overrides:
        data.update({str(k): float(v) for k, v in overrides.items()})
    return MappingProxyType(data)


def merged_thresholds(overrides: Mapping[str, float] | None = None) -> Mapping[str, float]:
    return _merged(DEFAULT_THRESHOLDS, overrides)


def merged_parameters(overrides: Mapping[str, float] | None = None) -> Mapping[str, float]:
    defaults = dict(DEFAULT_PARAMETERS)
    defaults.update(DEFAULT_STRATEGY_PARAMETERS)
    return _merged(MappingProxyType(defaults), overrides)


def merged_utility_weight_multipliers(overrides: Mapping[str, float] | None = None) -> Mapping[str, float]:
    return _merged(DEFAULT_UTILITY_WEIGHT_MULTIPLIERS, overrides)
