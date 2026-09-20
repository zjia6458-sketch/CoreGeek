from .geometry import (
    chebyshev_distance,
    is_adjacent8,
    neighbors8,
    angle_within_90,
)
from .catalog import (
    WEAPON_TYPES,
    RESOURCE_TYPES,
    TASK_ZONE_TYPES,
    NEUTRAL_BLOCKER_TYPES,
    BuildingRule,
    building_rule,
    building_max_hp,
    weapon_attack_range,
)

__all__ = [
    "chebyshev_distance",
    "is_adjacent8",
    "neighbors8",
    "angle_within_90",
    "WEAPON_TYPES",
    "RESOURCE_TYPES",
    "TASK_ZONE_TYPES",
    "NEUTRAL_BLOCKER_TYPES",
    "BuildingRule",
    "building_rule",
    "building_max_hp",
    "weapon_attack_range",
]

from .tasks import own_task_zones, task_zone_positions_for_task, available_task_zone_positions

from .build_area import (
    BuildAreaPolicy,
    BuildAreaType,
    StationDefenseBuildAreaPolicy,
    VerifiedBuildAreaPolicy,
    DEFAULT_BUILD_AREA_POLICY,
    distance_to_station_footprint,
    station_defense_cells,
    station_footprint_cells,
)

from .constants import (
    DAY_TURNS, NIGHT_TURNS, DAY_CYCLE_TURNS, MAX_DAYS, MAX_ROUNDS,
    SHARED_VISION_RANGE, MINE_COLLECTIONS_BEFORE_REFRESH,
    GLOBAL_WEAPON_LIMIT, WALL_LIMIT, TASK_REFRESH_COOLDOWN_ROUNDS,
    ROBOT_SUMMON_ORDER_DAILY_LIMIT, MAX_RESPONSE_ANOMALIES,
)
from .scoring import completed_task_score, partial_task_score, survival_day_score, kill_score
from .feedback import FeedbackClass, ActionExecutionFeedback, classify_role_action_result
