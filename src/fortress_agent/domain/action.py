from __future__ import annotations

from dataclasses import dataclass

from .state import Position

EntityId = str | int


@dataclass(frozen=True, slots=True)
class Action:
    actor_id: EntityId
    action_type: str


@dataclass(frozen=True, slots=True)
class MoveAction(Action):
    x: int
    y: int


@dataclass(frozen=True, slots=True)
class ExploreAction(Action):
    x: int
    y: int


@dataclass(frozen=True, slots=True)
class ResourceApproachAction(MoveAction):
    resource_id: EntityId


@dataclass(frozen=True, slots=True)
class GoalApproachAction(MoveAction):
    goal_kind: str
    goal_id: str
    goal_x: int
    goal_y: int


@dataclass(frozen=True, slots=True)
class GatherAction(Action):
    resource_id: EntityId


@dataclass(frozen=True, slots=True)
class AttackAction(Action):
    controller_id: EntityId
    targets: tuple[Position, ...]


@dataclass(frozen=True, slots=True)
class SellAction(Action):
    name: str
    num: int = 1


@dataclass(frozen=True, slots=True)
class BuyAction(Action):
    name: str
    num: int = 1


@dataclass(frozen=True, slots=True)
class BuildAction(Action):
    name: str
    target: Position = Position(0, 0)


@dataclass(frozen=True, slots=True)
class RemoveAction(Action):
    target: Position = Position(0, 0)


@dataclass(frozen=True, slots=True)
class AcceptTaskAction(Action):
    pass


@dataclass(frozen=True, slots=True)
class SubmitAnswerAction(Action):
    task_answer: str = ""


@dataclass(frozen=True, slots=True)
class SummonTreasureAction(Action):
    target: Position = Position(0, 0)
    items: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class UseAction(Action):
    name: str = ""
    target: Position | None = None


@dataclass(frozen=True, slots=True)
class DropAction(Action):
    name: str = ""


@dataclass(frozen=True, slots=True)
class GenericAction(Action):
    payload: tuple[tuple[str, object], ...] = ()
