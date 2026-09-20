from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Mapping

EntityId = str | int


@dataclass(frozen=True, slots=True)
class Position:
    x: int
    y: int


@dataclass(frozen=True, slots=True)
class ObservedCell:
    x: int
    y: int
    terrain: str | None = None


@dataclass(frozen=True, slots=True)
class InventoryItem:
    item_type: str
    amount: int


@dataclass(frozen=True, slots=True)
class CharacterState:
    actor_id: EntityId
    role: str
    hp: int
    max_hp: int | None
    position: Position
    backpack_capacity: int | None
    inventory: tuple[InventoryItem, ...]
    attack_power: int = 0
    attack_range: int = 0
    level: int | None = None
    cooldown: int = 0


@dataclass(frozen=True, slots=True)
class EnemyState:
    enemy_id: EntityId
    enemy_type: str
    hp: int
    max_hp: int | None
    attack: int | None
    attack_range: int | None
    score_value: int | None
    position: Position
    abnormal_state: str = ""
    target_team: str | None = None


@dataclass(frozen=True, slots=True)
class BuildingState:
    building_id: EntityId
    building_type: str
    position: Position
    hp: int | None
    max_hp: int | None
    owner: str | None
    cooldown_remaining: int
    attack_power: int = 0
    attack_range: int = 0
    level: int | None = None
    footprint_width: int = 1
    footprint_height: int = 1
    footprint_anchor: str = "cell"


@dataclass(frozen=True, slots=True)
class ResourceNodeState:
    resource_id: EntityId
    resource_type: str
    position: Position
    amount: int | None
    active: bool


@dataclass(frozen=True, slots=True)
class TaskState:
    task_id: EntityId
    task_type: str
    status: str
    position: Position | None
    reward: float | None
    standard_turns: int | None
    accepted_round: int | None
    payload: Mapping[str, Any]
    timeout_rounds: int | None = None


@dataclass(frozen=True, slots=True)
class NeutralZoneState:
    zone_type: str
    position: Position


@dataclass(frozen=True, slots=True)
class ShopItemState:
    name: str
    price: float


@dataclass(frozen=True, slots=True)
class ServerErrorState:
    error_code: int
    description: str


@dataclass(frozen=True, slots=True)
class WorldNewsState:
    official_news: str
    folk_legends: str


@dataclass(frozen=True, slots=True)
class GameState:
    round_id: int
    day: int
    phase: str
    phase_round: int | None
    turns_until_phase_change: int | None

    score_self: float
    score_opponent: float

    # Legacy field retained for compatibility with early framework versions.
    # It MUST NOT be populated from the current-round `errors` array because
    # the official interface does not state that `errors` is cumulative.
    anomaly_count: int

    characters: tuple[CharacterState, ...]
    enemies: tuple[EnemyState, ...]
    buildings: tuple[BuildingState, ...]
    resources: tuple[ResourceNodeState, ...]
    tasks: tuple[TaskState, ...]

    observed_cells: tuple[ObservedCell, ...]

    news: tuple[str, ...]
    rumors: tuple[str, ...]
    market_prices: Mapping[str, float]

    team_type: str | None = None
    team_id: str | None = None
    team_name: str | None = None
    gold_self: int = 0

    opponent_characters: tuple[CharacterState, ...] = ()
    neutral_zones: tuple[NeutralZoneState, ...] = ()
    weapon_shop: Mapping[str, float] = field(
        default_factory=lambda: MappingProxyType({})
    )

    world_news: WorldNewsState | None = None
    raw_llm_response: str = ""
    phase_task: str = ""
    last_command_result: str = ""
    last_summon_treasure_result: int | None = None

    last_round_role_action_results: Mapping[str, bool] = field(
        default_factory=lambda: MappingProxyType({})
    )
    server_errors: tuple[ServerErrorState, ...] = ()
    round_error_count: int = 0

    map_width: int = 41
    map_height: int = 32
    map_snapshot_complete: bool = False

    schema_version: str = "0.2.9"

    @staticmethod
    def readonly_mapping(data: Mapping[str, Any]) -> Mapping[str, Any]:
        return MappingProxyType(dict(data))
