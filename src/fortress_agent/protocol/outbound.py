from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

EntityId = str | int


class OutboundModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class PositionOut(OutboundModel):
    x: int = Field(ge=0, le=40)
    y: int = Field(ge=0, le=31)


class MoveCommand(OutboundModel):
    command: Literal["move"] = "move"
    actor_id: EntityId
    target: PositionOut


class AttackCommand(OutboundModel):
    command: Literal["attack"] = "attack"
    actor_id: EntityId
    target_id: EntityId | None = None
    target: PositionOut | None = None

    @model_validator(mode="after")
    def require_target(self):
        if self.target_id is None and self.target is None:
            raise ValueError("attack requires target_id or target")
        return self


class GatherCommand(OutboundModel):
    command: Literal["gather"] = "gather"
    actor_id: EntityId
    resource_id: EntityId


class BuildCommand(OutboundModel):
    command: Literal["build"] = "build"
    actor_id: EntityId
    building_type: str
    position: PositionOut


class DismantleCommand(OutboundModel):
    command: Literal["dismantle"] = "dismantle"
    actor_id: EntityId
    building_id: EntityId


class SellCommand(OutboundModel):
    command: Literal["sell"] = "sell"
    actor_id: EntityId
    item_type: str
    amount: int = Field(gt=0)


class BuyCommand(OutboundModel):
    command: Literal["buy"] = "buy"
    actor_id: EntityId
    item_type: str
    amount: int = Field(gt=0)


class TakeTaskCommand(OutboundModel):
    command: Literal["take_task"] = "take_task"
    actor_id: EntityId
    task_id: EntityId


class SubmitAnswerCommand(OutboundModel):
    command: Literal["submit_answer"] = "submit_answer"
    actor_id: EntityId
    task_id: EntityId
    answer: str = Field(min_length=1)


class SummonTreasureCommand(OutboundModel):
    command: Literal["summon_treasure"] = "summon_treasure"
    actor_id: EntityId
    altar_id: EntityId | None = None
    item_ids: tuple[EntityId, ...] = ()


class UseCommand(OutboundModel):
    command: Literal["use"] = "use"
    actor_id: EntityId
    item_id: EntityId
    target_id: EntityId | None = None


class DiscardCommand(OutboundModel):
    command: Literal["discard"] = "discard"
    actor_id: EntityId
    item_id: EntityId
    amount: int = Field(default=1, gt=0)


Command = Annotated[
    MoveCommand
    | AttackCommand
    | GatherCommand
    | BuildCommand
    | DismantleCommand
    | SellCommand
    | BuyCommand
    | TakeTaskCommand
    | SubmitAnswerCommand
    | SummonTreasureCommand
    | UseCommand
    | DiscardCommand,
    Field(discriminator="command"),
]


class GameActionResponse(OutboundModel):
    actions: tuple[Command, ...] = Field(min_length=1)
