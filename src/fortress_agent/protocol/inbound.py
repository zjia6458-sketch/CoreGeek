from __future__ import annotations

from typing import Any

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator

EntityId = str | int


class InboundModel(BaseModel):
    model_config = ConfigDict(
        extra="allow",
        frozen=True,
        populate_by_name=True,
    )


class PositionDTO(InboundModel):
    x: int = Field(ge=0, le=40)
    y: int = Field(ge=0, le=31)



class ObservedCellDTO(InboundModel):
    x: int = Field(ge=0, le=40)
    y: int = Field(ge=0, le=31)
    terrain: str | None = None


class CharacterDTO(InboundModel):
    actor_id: EntityId = Field(validation_alias=AliasChoices("actor_id", "id", "character_id"))
    role: str
    hp: int = Field(ge=0)
    max_hp: int | None = Field(default=None, ge=0)
    position: PositionDTO
    backpack_capacity: int | None = Field(default=None, ge=0)
    inventory: dict[str, int] = Field(default_factory=dict)

    @field_validator("inventory")
    @classmethod
    def validate_inventory(cls, value: dict[str, int]) -> dict[str, int]:
        if any(amount < 0 for amount in value.values()):
            raise ValueError("inventory amount must be >= 0")
        return value


class EnemyDTO(InboundModel):
    enemy_id: EntityId = Field(validation_alias=AliasChoices("enemy_id", "robot_id", "id"))
    enemy_type: str = Field(validation_alias=AliasChoices("enemy_type", "robot_type", "type"))
    hp: int = Field(ge=0)
    max_hp: int | None = Field(default=None, ge=0)
    attack: int | None = Field(default=None, ge=0)
    score_value: int | None = Field(
        default=None,
        ge=0,
        validation_alias=AliasChoices("score_value", "score", "points"),
    )
    position: PositionDTO


class BuildingDTO(InboundModel):
    building_id: EntityId = Field(validation_alias=AliasChoices("building_id", "id"))
    building_type: str = Field(validation_alias=AliasChoices("building_type", "type"))
    position: PositionDTO
    hp: int | None = Field(default=None, ge=0)
    max_hp: int | None = Field(default=None, ge=0)
    owner: str | None = None
    cooldown_remaining: int = Field(default=0, ge=0)


class ResourceNodeDTO(InboundModel):
    resource_id: EntityId = Field(validation_alias=AliasChoices("resource_id", "id"))
    resource_type: str = Field(validation_alias=AliasChoices("resource_type", "type"))
    position: PositionDTO
    amount: int | None = Field(default=None, ge=0)
    active: bool = True


class TaskDTO(InboundModel):
    task_id: EntityId = Field(validation_alias=AliasChoices("task_id", "id"))
    task_type: str = Field(validation_alias=AliasChoices("task_type", "type"))
    status: str = "available"
    position: PositionDTO | None = None
    reward: float | None = None
    standard_turns: int | None = Field(default=None, ge=0)
    accepted_round: int | None = Field(default=None, ge=0)
    payload: dict[str, Any] = Field(default_factory=dict)


class GameStateDTO(InboundModel):
    round_id: int = Field(ge=0, validation_alias=AliasChoices("round_id", "round", "turn"))
    day: int = Field(ge=1)
    phase: str
    phase_round: int | None = Field(default=None, ge=0)
    turns_until_phase_change: int | None = Field(
        default=None,
        ge=0,
        validation_alias=AliasChoices(
            "turns_until_phase_change",
            "turns_until_night",
            "phase_remaining",
        ),
    )

    score_self: float = Field(
        default=0.0,
        validation_alias=AliasChoices("score_self", "my_score", "self_score"),
    )
    score_opponent: float = Field(
        default=0.0,
        validation_alias=AliasChoices("score_opponent", "opponent_score", "enemy_score"),
    )
    anomaly_count: int = Field(default=0, ge=0)

    characters: list[CharacterDTO] = Field(
        default_factory=list,
        validation_alias=AliasChoices("characters", "actors"),
    )
    enemies: list[EnemyDTO] = Field(
        default_factory=list,
        validation_alias=AliasChoices("enemies", "robots"),
    )
    buildings: list[BuildingDTO] = Field(default_factory=list)
    resources: list[ResourceNodeDTO] = Field(
        default_factory=list,
        validation_alias=AliasChoices("resources", "resource_nodes", "mines"),
    )
    tasks: list[TaskDTO] = Field(default_factory=list)

    observed_cells: list[ObservedCellDTO] = Field(
        default_factory=list,
        validation_alias=AliasChoices(
            "observed_cells",
            "visible_cells",
            "cells",
        ),
    )

    news: list[str] = Field(default_factory=list)
    rumors: list[str] = Field(default_factory=list)
    market_prices: dict[str, float] = Field(
        default_factory=dict,
        validation_alias=AliasChoices("market_prices", "prices"),
    )
