from __future__ import annotations

# Time
DAY_TURNS = 70
NIGHT_TURNS = 60
DAY_CYCLE_TURNS = DAY_TURNS + NIGHT_TURNS
MAX_DAYS = 10
MAX_ROUNDS = 1300

# Map / observation. The current official map is 41x32, while runtime bounds
# continue to use mapInfo.width/height so the engine is not needlessly fixed.
REFERENCE_MAP_WIDTH = 41
REFERENCE_MAP_HEIGHT = 32
SHARED_VISION_RANGE = 4

# Economy / construction
MINE_COLLECTIONS_BEFORE_REFRESH = 10
GLOBAL_WEAPON_LIMIT = 3
WALL_LIMIT = 20
TASK_REFRESH_COOLDOWN_ROUNDS = 30
ROBOT_SUMMON_ORDER_DAILY_LIMIT = 10

# Judger safety
MAX_RESPONSE_ANOMALIES = 5
CONNECT_TIMEOUT_SECONDS = 10
RESPONSE_TIMEOUT_SECONDS = 5

# Combat / interaction
ROCKET_COOLDOWN_ROUNDS = 3
ROBOT_ATTACK_RANGE = 3
