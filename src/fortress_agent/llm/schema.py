from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


StrategicMode = Literal[
    "keep",
    "explore",
    "task",
    "prepare",
    "defense",
    "recovery",
    "aggressive",
    "conservative",
]

RegionHint = Literal[
    "north",
    "south",
    "east",
    "west",
    "center",
    "unknown",
]

ClaimKind = Literal[
    "location_hint",
    "resource_hint",
    "requirement",
    "route_hint",
    "market_hint",
    "threat_hint",
    "unknown",
]

ObjectiveType = Literal[
    "explore_region",
    "visit_position",
    "collect_items",
    "take_task",
    "preserve_resources",
    "prepare_defense",
    "observe",
]


class LLMStrictModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
    )


class StrategicPosition(LLMStrictModel):
    x: int = Field(ge=0, le=40)
    y: int = Field(ge=0, le=31)


class KnowledgeClaim(LLMStrictModel):
    kind: ClaimKind
    subject: str = Field(min_length=1, max_length=120)
    relation: str = Field(min_length=1, max_length=120)
    object: str = Field(min_length=1, max_length=240)
    confidence: float = Field(ge=0.0, le=1.0)


class StrategicObjective(LLMStrictModel):
    objective_type: ObjectiveType
    priority: float = Field(ge=0.0, le=1.0)
    description: str = Field(min_length=1, max_length=240)

    target_position: StrategicPosition | None = None
    target_region: RegionHint = "unknown"

    required_items: tuple[str, ...] = Field(
        default=(),
        max_length=8,
    )


class StrategicAdvisory(LLMStrictModel):
    schema_version: Literal["1.0"] = "1.0"

    source_round: int = Field(ge=1)

    recommended_mode: StrategicMode = "keep"
    mode_strength: float = Field(ge=0.0, le=1.0)
    confidence: float = Field(ge=0.0, le=1.0)

    expires_after_rounds: int = Field(
        default=130,
        ge=0,
        le=1300,
    )

    claims: tuple[KnowledgeClaim, ...] = Field(
        default=(),
        max_length=12,
    )
    objectives: tuple[StrategicObjective, ...] = Field(
        default=(),
        max_length=8,
    )

    short_reason: str = Field(
        default="",
        max_length=500,
    )

    @property
    def effective_strength(self) -> float:
        return self.mode_strength * self.confidence
