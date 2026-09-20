from __future__ import annotations

from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
)


NonEmptyString = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1),
]


class ServerOutboundModel(BaseModel):
    # The wire schema is closed: unknown fields must never be emitted.
    # Do not use global strict=True because JSON arrays naturally arrive as
    # Python lists while immutable internal models use tuples.
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
    )


class ServerTargetPos(ServerOutboundModel):
    # Upper bounds are state-dependent (`mapInfo.width/height`) and are
    # enforced by FinalResponseValidator rather than hard-coded here.
    x: int = Field(ge=0)
    y: int = Field(ge=0)


class MoveRoleCommand(ServerOutboundModel):
    action: Literal["move"] = "move"
    targetPos: tuple[ServerTargetPos, ...] = Field(min_length=1, max_length=1)


class AttackRoleCommand(ServerOutboundModel):
    action: Literal["attack"] = "attack"
    controllerId: NonEmptyString
    targetPos: tuple[ServerTargetPos, ...] = Field(min_length=1)


class SellRoleCommand(ServerOutboundModel):
    action: Literal["sell"] = "sell"
    name: NonEmptyString
    num: int = Field(default=1, gt=0)


class BuyRoleCommand(ServerOutboundModel):
    action: Literal["buy"] = "buy"
    name: NonEmptyString
    num: int = Field(default=1, gt=0)


class BuildRoleCommand(ServerOutboundModel):
    action: Literal["build"] = "build"
    name: NonEmptyString
    targetPos: tuple[ServerTargetPos, ...] = Field(min_length=1, max_length=1)


class RemoveRoleCommand(ServerOutboundModel):
    action: Literal["remove"] = "remove"
    targetPos: tuple[ServerTargetPos, ...] = Field(min_length=1, max_length=1)


class AcceptTaskRoleCommand(ServerOutboundModel):
    action: Literal["acceptTask"] = "acceptTask"


class SubmitAnswerRoleCommand(ServerOutboundModel):
    action: Literal["submitAnswer"] = "submitAnswer"
    taskAnswer: NonEmptyString


class SummonTreasureRoleCommand(ServerOutboundModel):
    action: Literal["summonTreasure"] = "summonTreasure"
    targetPos: tuple[ServerTargetPos, ...] = Field(min_length=1, max_length=1)
    item: tuple[NonEmptyString, ...] = Field(min_length=1)


class UseRoleCommand(ServerOutboundModel):
    action: Literal["use"] = "use"
    name: NonEmptyString

    # Some items target a cell (WallFixer, DizzyWeapon, Bomb, voucher);
    # others do not (Medicine, summon order). Empty/None is therefore legal.
    targetPos: tuple[ServerTargetPos, ...] | None = None

    @field_validator("targetPos", mode="before")
    @classmethod
    def empty_target_list_to_none(cls, value):
        if value == [] or value == ():
            return None
        return value


class DropRoleCommand(ServerOutboundModel):
    action: Literal["drop"] = "drop"
    name: NonEmptyString


class CollectRoleCommand(ServerOutboundModel):
    action: Literal["collect"] = "collect"
    targetPos: tuple[ServerTargetPos, ...] = Field(min_length=1, max_length=1)


RoleCommand = Annotated[
    MoveRoleCommand
    | AttackRoleCommand
    | SellRoleCommand
    | BuyRoleCommand
    | BuildRoleCommand
    | RemoveRoleCommand
    | AcceptTaskRoleCommand
    | SubmitAnswerRoleCommand
    | SummonTreasureRoleCommand
    | UseRoleCommand
    | DropRoleCommand
    | CollectRoleCommand,
    Field(discriminator="action"),
]


class ServerCommandResponse(ServerOutboundModel):
    # Empty map is deliberately legal. When no verified safe command exists,
    # emitting no role command is safer than fabricating an invalid one.
    roleCommandMap: dict[str, RoleCommand] = Field(default_factory=dict)

    # The sample protocol explicitly allows these to be empty.
    prompt: str = ""
    executeCmd: str = ""

    @field_validator("prompt", "executeCmd", mode="before")
    @classmethod
    def nullable_text_to_empty(cls, value):
        return "" if value is None else value
