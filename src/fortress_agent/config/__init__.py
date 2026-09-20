"""运行时可调策略配置。

官方游戏硬规则仍位于 :mod:`fortress_agent.game_rules`；本包只保存我方策略的
软阈值/权重。软参数允许配置和小幅在线学习，绝不能绕过 Legal/FinalValidator。
"""

from .tuning import (
    DEFAULT_PARAMETERS,
    DEFAULT_THRESHOLDS,
    DEFAULT_UTILITY_WEIGHT_MULTIPLIERS,
    RuntimeLearningConfig,
    merged_parameters,
    merged_thresholds,
    merged_utility_weight_multipliers,
)

__all__ = [
    "DEFAULT_PARAMETERS",
    "DEFAULT_THRESHOLDS",
    "DEFAULT_UTILITY_WEIGHT_MULTIPLIERS",
    "RuntimeLearningConfig",
    "merged_parameters",
    "merged_thresholds",
    "merged_utility_weight_multipliers",
]
