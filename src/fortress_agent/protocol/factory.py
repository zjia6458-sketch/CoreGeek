from __future__ import annotations

from .outbound import (
    AttackCommand,
    BuildCommand,
    BuyCommand,
    DiscardCommand,
    DismantleCommand,
    GatherCommand,
    MoveCommand,
    PositionOut,
    SellCommand,
    SubmitAnswerCommand,
    SummonTreasureCommand,
    TakeTaskCommand,
    UseCommand,
)


class CommandFactory:
    @staticmethod
    def move(actor_id, x: int, y: int) -> MoveCommand:
        return MoveCommand(actor_id=actor_id, target=PositionOut(x=x, y=y))

    @staticmethod
    def attack(actor_id, *, target_id=None, x: int | None = None, y: int | None = None):
        target = None
        if x is not None or y is not None:
            if x is None or y is None:
                raise ValueError("both x and y are required for positional attack")
            target = PositionOut(x=x, y=y)
        return AttackCommand(actor_id=actor_id, target_id=target_id, target=target)

    @staticmethod
    def gather(actor_id, resource_id) -> GatherCommand:
        return GatherCommand(actor_id=actor_id, resource_id=resource_id)

    @staticmethod
    def build(actor_id, building_type: str, x: int, y: int) -> BuildCommand:
        return BuildCommand(
            actor_id=actor_id,
            building_type=building_type,
            position=PositionOut(x=x, y=y),
        )

    @staticmethod
    def dismantle(actor_id, building_id) -> DismantleCommand:
        return DismantleCommand(actor_id=actor_id, building_id=building_id)

    @staticmethod
    def sell(actor_id, item_type: str, amount: int) -> SellCommand:
        return SellCommand(actor_id=actor_id, item_type=item_type, amount=amount)

    @staticmethod
    def buy(actor_id, item_type: str, amount: int) -> BuyCommand:
        return BuyCommand(actor_id=actor_id, item_type=item_type, amount=amount)

    @staticmethod
    def take_task(actor_id, task_id) -> TakeTaskCommand:
        return TakeTaskCommand(actor_id=actor_id, task_id=task_id)

    @staticmethod
    def submit_answer(actor_id, task_id, answer: str) -> SubmitAnswerCommand:
        return SubmitAnswerCommand(actor_id=actor_id, task_id=task_id, answer=answer)

    @staticmethod
    def summon_treasure(actor_id, *, altar_id=None, item_ids=()) -> SummonTreasureCommand:
        return SummonTreasureCommand(
            actor_id=actor_id,
            altar_id=altar_id,
            item_ids=tuple(item_ids),
        )

    @staticmethod
    def use(actor_id, item_id, *, target_id=None) -> UseCommand:
        return UseCommand(actor_id=actor_id, item_id=item_id, target_id=target_id)

    @staticmethod
    def discard(actor_id, item_id, amount: int = 1) -> DiscardCommand:
        return DiscardCommand(actor_id=actor_id, item_id=item_id, amount=amount)
