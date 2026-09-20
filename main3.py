#!/usr/bin/env python3
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# FortressAgent 生产配置入口
# ---------------------------------------------------------------------------
# 约定：官方游戏硬规则（70/60 昼夜、武器价格、墙上限等）放在 game_rules 中，
# 不允许在线学习修改；下面只配置“我方策略软参数”。所有参数都可在比赛前调整。

LOG_MODE = "medium"  # "low" | "medium" | "high"

# 判题器 5 秒超时的两层保护。
INTERNAL_DEADLINE_SECONDS = 3.2
HTTP_OUTER_TIMEOUT_SECONDS = 4.2

# ---------------------------- 阶段/阈值配置 ----------------------------
# prepare：角色开始回基地/武器控制位的窗口。它与采矿紧急撤离是不同概念。
PREPARE_MARGIN_ROUNDS = 20
# 建墙施工预留窗口：距离黑夜剩余 <=25 回合时，如果背包矿物已经达到返场阈值，
# Worker 优先把材料运回基地并落墙。该窗口可以早于 prepare。
WALL_BUILD_RESERVE_ROUNDS = 25
# 采矿紧急窗口：距离黑夜 <=8 回合时不再开启新矿点；已经站在矿旁的 Worker
# 允许额外 collect 1 次，然后必须离开。可按实战地图大小调整。
MINING_EMERGENCY_ROUNDS = 8
# 白天开始后的前 N 回合尽量把矿工背包填满；此阶段高水位阈值不阻止继续采矿。
EARLY_DAY_FULL_BACKPACK_ROUNDS = 30
# 非白天早期时，背包使用率达到该值后停止开启新的远距离采矿行程。
BACKPACK_HIGH_WATERMARK_RATIO = 0.80
# 进入建墙预留窗口后，只要矿物占背包达到该比例就开始返场，不必等背包满。
NEAR_NIGHT_MINERAL_RETURN_RATIO = 0.35
# 正常 stone 运输批量；当前矿仍在时尽量继续采完，矿消失/离矿后达到该数量再返场。
STONE_BATCH_SIZE = 4
# 每名 Worker 每回合最多保留多少个资源目标，限制 A* 搜索宽度。
RESOURCE_CANDIDATE_LIMIT = 2
# 夜战候选搜索宽度：机器人很多时限制组合数量，避免耗尽 5 秒预算。
ATTACK_TARGET_POOL_LIMIT = 12
ATTACK_TARGET_SET_LIMIT = 32
# 建造返场只检查前 N 个高优先级目标，避免 20 个墙位逐个 A*。
BUILD_TARGET_LOOKAHEAD = 4
# 三面墙 Blueprint 固定 16 格；只有 16/16 才认为主动防线建设完成。
WALL_DAY1_TARGET = 16
WALL_TARGET_INCREMENT_PER_DAY = 0
WALL_TARGET_MAX = 16
# 一个资源/商店/施工目标一旦真正发出移动，至少保持 N 回合；目标失效/危险可提前释放。
RESOURCE_COMMITMENT_MIN_ROUNDS = 4

# ---------------------------- 夜间安全采矿配置 ----------------------------
# 矿点可以位于地图任意位置；该值定义撤离时低风险边缘安全区的宽度。
NIGHT_EDGE_MINING_MARGIN_CELLS = 5
# RobotThreatField 向未来预测多少回合。
NIGHT_ROBOT_PREDICTION_HORIZON = 12
# 最近真实移动方向先延续几步，再重新按最快路径向 Station 收缩。
NIGHT_ROBOT_OBSERVED_HEADING_STEPS = 3
# 硬安全圈 = attackRange + HARD；硬圈内 Safe A* 绝不扩展。
NIGHT_ROBOT_HARD_SAFETY_MARGIN = 1
# 软安全圈 = attackRange + SOFT；软圈内仍可搜索，但路径代价显著增大。
NIGHT_ROBOT_SOFT_SAFETY_MARGIN = 3
# 夜间路径最大规划步数，限制搜索时间。
NIGHT_SAFE_PATH_MAX_STEPS = 64
# Worker 低于该生命比例禁止夜间离站采矿。
NIGHT_WORKER_MIN_HP_RATIO = 0.55
# 到达夜间矿后必须至少还能安全停留这么多回合，否则不出发。
NIGHT_RESOURCE_MIN_SAFE_HOLD_ROUNDS = 3
# 生命低于 30% 时进入治疗流程（购买/使用 Medicine）。
CHARACTER_MEDICINE_HP_RATIO = 0.30
# Day2+ 围墙低于 50% HP 时进入维护；有 stone 且低于 35% 时优先拆建，
# 其余低血量围墙才进入需花金币购买 WallFixer 的修复流程。
WALL_FIXER_HP_RATIO = 0.50

STRATEGY_THRESHOLDS = {
    "prepare_margin_rounds": float(PREPARE_MARGIN_ROUNDS),
    "wall_build_reserve_rounds": float(WALL_BUILD_RESERVE_ROUNDS),
    "mining_emergency_rounds": float(MINING_EMERGENCY_ROUNDS),
    "early_day_full_backpack_rounds": float(EARLY_DAY_FULL_BACKPACK_ROUNDS),
    "backpack_high_watermark_ratio": float(BACKPACK_HIGH_WATERMARK_RATIO),
    "near_night_mineral_return_ratio": float(NEAR_NIGHT_MINERAL_RETURN_RATIO),
    "nonstone_sell_batch_size": 4.0,
    "stone_batch_size": float(STONE_BATCH_SIZE),
    "resource_candidate_limit": float(RESOURCE_CANDIDATE_LIMIT),
    "attack_target_pool_limit": float(ATTACK_TARGET_POOL_LIMIT),
    "attack_target_set_limit": float(ATTACK_TARGET_SET_LIMIT),
    "build_target_lookahead": float(BUILD_TARGET_LOOKAHEAD),
    "wall_day1_target": float(WALL_DAY1_TARGET),
    "wall_target_increment_per_day": float(WALL_TARGET_INCREMENT_PER_DAY),
    "wall_target_max": float(WALL_TARGET_MAX),
    "resource_commitment_min_rounds": float(RESOURCE_COMMITMENT_MIN_ROUNDS),
    "night_edge_mining_margin_cells": float(NIGHT_EDGE_MINING_MARGIN_CELLS),
    "night_robot_prediction_horizon": float(NIGHT_ROBOT_PREDICTION_HORIZON),
    "night_robot_observed_heading_steps": float(NIGHT_ROBOT_OBSERVED_HEADING_STEPS),
    "night_robot_hard_safety_margin": float(NIGHT_ROBOT_HARD_SAFETY_MARGIN),
    "night_robot_soft_safety_margin": float(NIGHT_ROBOT_SOFT_SAFETY_MARGIN),
    "night_safe_path_max_steps": float(NIGHT_SAFE_PATH_MAX_STEPS),
    "night_worker_min_hp_ratio": float(NIGHT_WORKER_MIN_HP_RATIO),
    "night_resource_min_safe_hold_rounds": float(NIGHT_RESOURCE_MIN_SAFE_HOLD_ROUNDS),
    "wall_rebuild_hp_ratio": 0.35,
    "character_medicine_hp_ratio": float(CHARACTER_MEDICINE_HP_RATIO),
    "wall_fixer_hp_ratio": float(WALL_FIXER_HP_RATIO),
}

# ---------------------------- 资源选择公式 ----------------------------
# resource_score = RESOURCE_DISTANCE_WEIGHT / (distance + 1)
#                  + market_value * RESOURCE_MARKET_VALUE_WEIGHT
#                  + commitment_bonus + wall_bonus
# 默认距离权重明显大于价格权重：优先采附近矿，而不是横穿地图追高价矿。
RESOURCE_DISTANCE_WEIGHT = 8.00
RESOURCE_MARKET_VALUE_WEIGHT = 0.10
# 三面墙 16/16 完成后进入赚钱/升级循环：提高矿价权重，距离仍保留成本。
POST_WALL_RESOURCE_DISTANCE_WEIGHT = 2.00
POST_WALL_RESOURCE_MARKET_VALUE_WEIGHT = 1.00
# 已经选定的当前矿点获得黏性奖励，减少连续回合切换矿点。
RESOURCE_COMMITMENT_BONUS = 3.00
# 围墙目标未完成时 stone 的额外奖励。
RESOURCE_WALL_STONE_BONUS = 5.00
RESOURCE_BUILDER_STONE_BONUS = 1.00
RESOURCE_BUILDER_NONSTONE_PENALTY = 1.00
# Worker 已经站在当前矿旁时继续 collect 的奖励，用于“尽量采完当前矿”。
GATHER_CURRENT_MINE_BONUS = 2.50
# Safe A* 风险成本与夜间矿点安全评分。
NIGHT_THREAT_PATH_WEIGHT = 6.0
NIGHT_HARD_RISK_THRESHOLD = 1.0
NIGHT_RESOURCE_MAX_RISK = 0.35
NIGHT_ESCAPE_MAX_RISK = 0.45
NIGHT_RESOURCE_SAFETY_WEIGHT = 10.0
NIGHT_RESOURCE_DISTANCE_WEIGHT = 7.0
NIGHT_RESOURCE_VALUE_WEIGHT = 0.08

# ---------------------------- StrategyGraph / Profile 参数 ----------------------------
# 下面全部是“我方策略软参数”，不是官方规则。
# StrategyProfile 的基准权重决定同一 Reward 分量在不同战略下的重要程度；
# UTILITY_WEIGHT_MULTIPLIERS 则在此基准上再乘一个全局/在线倍率。
STRATEGY_PROFILE_PARAMETERS = {
    # LLM 长周期建议至少达到该有效强度才允许改变 daytime strategy branch。
    "strategy_llm_advisory_threshold": 0.45,
    # Strategy activator 的 score / priority。priority 更高者先获得战略控制权。
    "strategy_night_activation_score": 1.0,
    "strategy_night_activation_priority": 1000.0,
    "strategy_prepare_activation_score": 1.0,
    "strategy_prepare_activation_priority": 900.0,
    "strategy_active_task_activation_score": 1.0,
    "strategy_active_task_activation_priority": 950.0,
    "strategy_day_default_activation_score": 0.10,
    "strategy_day_default_activation_priority": 100.0,

    # defense：夜间生存/风险优先。
    "strategy_defense_weight_survival": 2.50,
    "strategy_defense_weight_risk": 2.00,
    "strategy_defense_weight_score": 1.20,
    "strategy_defense_risk_multiplier": 1.50,
    "strategy_defense_minimum_action_utility": 0.50,
    "strategy_defense_objective_protect_base_priority": 1.00,

    # prepare：站位和生存优先于探索。
    "strategy_prepare_weight_position": 1.50,
    "strategy_prepare_weight_survival": 1.50,
    "strategy_prepare_weight_information": 0.25,
    "strategy_prepare_risk_multiplier": 1.25,
    "strategy_prepare_minimum_action_utility": 0.00,
    "strategy_prepare_objective_return_and_prepare_priority": 1.00,

    # active_task：Pioneer 任务优先，但 Worker 仍保留经济/建设。
    "strategy_active_task_weight_task": 3.00,
    "strategy_active_task_weight_economy": 1.60,
    "strategy_active_task_weight_survival": 1.20,
    "strategy_active_task_weight_information": 0.50,
    "strategy_active_task_weight_position": 1.20,
    "strategy_active_task_objective_complete_active_task_priority": 1.00,

    # daytime economy / exploration / LLM branches。
    "strategy_economy_weight_economy": 1.60,
    "strategy_economy_weight_information": 0.80,
    "strategy_economy_weight_position": 1.00,
    "strategy_economy_weight_task": 1.80,
    "strategy_economy_minimum_action_utility": 0.00,
    "strategy_economy_objective_increase_economy_priority": 0.90,

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
}

STRATEGY_PARAMETERS = {
    **STRATEGY_PROFILE_PARAMETERS,
    "resource_distance_weight": RESOURCE_DISTANCE_WEIGHT,
    "resource_market_value_weight": RESOURCE_MARKET_VALUE_WEIGHT,
    "post_wall_resource_distance_weight": POST_WALL_RESOURCE_DISTANCE_WEIGHT,
    "post_wall_resource_market_value_weight": POST_WALL_RESOURCE_MARKET_VALUE_WEIGHT,
    "resource_commitment_bonus": RESOURCE_COMMITMENT_BONUS,
    "resource_wall_stone_bonus": RESOURCE_WALL_STONE_BONUS,
    "resource_builder_stone_bonus": RESOURCE_BUILDER_STONE_BONUS,
    "resource_builder_nonstone_penalty": RESOURCE_BUILDER_NONSTONE_PENALTY,
    "gather_current_mine_bonus": GATHER_CURRENT_MINE_BONUS,
    "night_threat_path_weight": NIGHT_THREAT_PATH_WEIGHT,
    "night_hard_risk_threshold": NIGHT_HARD_RISK_THRESHOLD,
    "night_resource_max_risk": NIGHT_RESOURCE_MAX_RISK,
    "night_escape_max_risk": NIGHT_ESCAPE_MAX_RISK,
    "night_resource_safety_weight": NIGHT_RESOURCE_SAFETY_WEIGHT,
    "night_resource_distance_weight": NIGHT_RESOURCE_DISTANCE_WEIGHT,
    "night_resource_value_weight": NIGHT_RESOURCE_VALUE_WEIGHT,
}

# ---------------------------- Utility 倍率 ----------------------------
# 最终 Utility 的有效权重 = StrategyProfile 基准权重 × 下列运行时倍率。
# 1.0 表示不改变策略基准。在线学习只能小幅修改允许的软倍率。
UTILITY_WEIGHT_MULTIPLIERS = {
    "score": 1.0,
    "survival": 1.0,
    "economy": 1.0,
    "information": 1.0,
    "position": 1.0,
    "task": 1.0,
    "time_cost": 1.0,
    "risk": 1.0,
}

# ---------------------------- 运行时轻量学习 ----------------------------
RUNTIME_LEARNING_ENABLED = True
# 首次允许更新的回合；随后按 UPDATE_INTERVAL 周期尝试。
RUNTIME_LEARNING_FIRST_UPDATE_ROUND = 20
# 每隔多少回合尝试一次更新。更新只发生在已有足够 Experience/Outcome 时。
RUNTIME_LEARNING_UPDATE_INTERVAL_ROUNDS = 20
# 每个更新点最多提升一个 patch，避免多个权重同时变化导致策略震荡。
RUNTIME_LEARNING_MAX_PATCHES_PER_UPDATE = 1
# learner 提案置信度低于该值不自动应用。
RUNTIME_LEARNING_MIN_CONFIDENCE = 0.55
# 单次学习变化的上限。注意：学习结果最终不会保存绝对 delta，而会换算成
# “相对 Base Config 的 Learned Overlay 比例”。例如 Base=4、学到 +0.2，
# 实际保存 +5%；若未来 Base 改为 8，同一 +5% 自动变成 +0.4。
# 当前不做 JSONL 持久化，进程重启后 Overlay 从空开始。
RUNTIME_LEARNING_MAX_RELATIVE_CHANGE = 0.10
RUNTIME_LEARNING_MAX_ABSOLUTE_CHANGE = 1.0

# PrepareMarginLearner：至少积累多少个 prepare Outcome 后才允许调整。
RUNTIME_LEARNING_PREPARE_MIN_SAMPLES = 5
RUNTIME_LEARNING_PREPARE_STEP_ROUNDS = 1.0
RUNTIME_LEARNING_PREPARE_MIN_ROUNDS = 8.0
RUNTIME_LEARNING_PREPARE_MAX_ROUNDS = 30.0
RUNTIME_LEARNING_PREPARE_NEGATIVE_REWARD_THRESHOLD = -0.5
RUNTIME_LEARNING_PREPARE_POSITIVE_REWARD_THRESHOLD = 2.0
# Gather economy multiplier 学习参数；倍率限制在 [0.75, 1.25] 内，避免大幅漂移。
RUNTIME_LEARNING_ECONOMY_MIN_SAMPLES = 5
RUNTIME_LEARNING_ECONOMY_RATE = 0.05
RUNTIME_LEARNING_ECONOMY_MIN = 0.75
RUNTIME_LEARNING_ECONOMY_MAX = 1.25
RUNTIME_LEARNING_ECONOMY_ERROR_DEADBAND = 0.5

# MOVE 执行失败后的全角色短期坐标保护。
MOVE_FAILURE_GLOBAL_BAN_ROUNDS = 3

# 官方建造代价默认由 game_rules 提供；仅特殊赛图/测试时覆盖。
BUILD_RECIPES: dict[str, dict[str, object]] | None = None

# 2x2 Station 自动推导 0/1/2 防御建造环；以下仅作为特殊地图附加合法区。
WEAPON_BUILD_CELLS: tuple[tuple[int, int], ...] = ()
WALL_BUILD_CELLS: tuple[tuple[int, int], ...] = ()
WEAPON_BUILD_ZONE_TYPES: tuple[str, ...] = ()
WALL_BUILD_ZONE_TYPES: tuple[str, ...] = ()


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("Usage: python main3.py <port>")
    try:
        port = int(sys.argv[1])
    except ValueError as exc:
        raise SystemExit("port must be an integer") from exc
    if not (1 <= port <= 65535):
        raise SystemExit("port must be between 1 and 65535")

    root = Path(__file__).resolve().parent
    os.chdir(root)
    src = root / "src"
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))

    normalized_log_mode = str(LOG_MODE).strip().lower()
    logging.basicConfig(
        stream=sys.stdout,
        level=logging.INFO,
        format=(
            "%(asctime)s | %(levelname)s | %(message)s"
            if normalized_log_mode in {"high", "full"}
            else "%(message)s"
        ),
    )
    logger = logging.getLogger()

    from agent.server import serve
    from fortress_agent.config.tuning import RuntimeLearningConfig

    if normalized_log_mode in {"high", "full"}:
        logger.info(
            '{"channel":"system","event":"server_starting",'
            '"host":"0.0.0.0","port":%d,"log_mode":"%s"}',
            port,
            LOG_MODE,
        )
    serve(
        port,
        log_mode=LOG_MODE,
        build_recipes=BUILD_RECIPES,
        weapon_build_cells=WEAPON_BUILD_CELLS,
        wall_build_cells=WALL_BUILD_CELLS,
        weapon_build_zone_types=WEAPON_BUILD_ZONE_TYPES,
        wall_build_zone_types=WALL_BUILD_ZONE_TYPES,
        move_failure_global_ban_rounds=MOVE_FAILURE_GLOBAL_BAN_ROUNDS,
        hard_deadline_seconds=INTERNAL_DEADLINE_SECONDS,
        http_outer_timeout_seconds=HTTP_OUTER_TIMEOUT_SECONDS,
        strategy_thresholds=STRATEGY_THRESHOLDS,
        strategy_parameters=STRATEGY_PARAMETERS,
        utility_weight_multipliers=UTILITY_WEIGHT_MULTIPLIERS,
        runtime_learning_config=RuntimeLearningConfig(
            enabled=RUNTIME_LEARNING_ENABLED,
            first_update_round=RUNTIME_LEARNING_FIRST_UPDATE_ROUND,
            update_interval_rounds=RUNTIME_LEARNING_UPDATE_INTERVAL_ROUNDS,
            max_patches_per_update=RUNTIME_LEARNING_MAX_PATCHES_PER_UPDATE,
            min_confidence=RUNTIME_LEARNING_MIN_CONFIDENCE,
            max_relative_change=RUNTIME_LEARNING_MAX_RELATIVE_CHANGE,
            max_absolute_change=RUNTIME_LEARNING_MAX_ABSOLUTE_CHANGE,
            prepare_min_samples=RUNTIME_LEARNING_PREPARE_MIN_SAMPLES,
            prepare_step_rounds=RUNTIME_LEARNING_PREPARE_STEP_ROUNDS,
            prepare_min_rounds=RUNTIME_LEARNING_PREPARE_MIN_ROUNDS,
            prepare_max_rounds=RUNTIME_LEARNING_PREPARE_MAX_ROUNDS,
            prepare_negative_reward_threshold=RUNTIME_LEARNING_PREPARE_NEGATIVE_REWARD_THRESHOLD,
            prepare_positive_reward_threshold=RUNTIME_LEARNING_PREPARE_POSITIVE_REWARD_THRESHOLD,
            economy_min_samples=RUNTIME_LEARNING_ECONOMY_MIN_SAMPLES,
            economy_learning_rate=RUNTIME_LEARNING_ECONOMY_RATE,
            economy_multiplier_min=RUNTIME_LEARNING_ECONOMY_MIN,
            economy_multiplier_max=RUNTIME_LEARNING_ECONOMY_MAX,
            economy_error_deadband=RUNTIME_LEARNING_ECONOMY_ERROR_DEADBAND,
        ),
    )


if __name__ == "__main__":
    main()
