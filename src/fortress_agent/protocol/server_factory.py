from __future__ import annotations

from .server_outbound import (
    AcceptTaskRoleCommand,
    AttackRoleCommand,
    BuildRoleCommand,
    BuyRoleCommand,
    CollectRoleCommand,
    DropRoleCommand,
    MoveRoleCommand,
    RemoveRoleCommand,
    SellRoleCommand,
    ServerTargetPos,
    SubmitAnswerRoleCommand,
    SummonTreasureRoleCommand,
    UseRoleCommand,
)


def _positions(points):
    return tuple(
        ServerTargetPos(x=x, y=y)
        for x, y in points
    )


class ServerCommandFactory:
    @staticmethod
    def move(*points: tuple[int, int]) -> MoveRoleCommand:
        return MoveRoleCommand(
            targetPos=_positions(points),
        )

    @staticmethod
    def attack(
        *,
        controller_id: str | int,
        points: tuple[tuple[int, int], ...],
    ) -> AttackRoleCommand:
        return AttackRoleCommand(
            controllerId=str(controller_id),
            targetPos=_positions(points),
        )

    @staticmethod
    def sell(
        name: str,
        num: int,
    ) -> SellRoleCommand:
        return SellRoleCommand(name=name, num=num)

    @staticmethod
    def buy(
        name: str,
        num: int,
    ) -> BuyRoleCommand:
        return BuyRoleCommand(name=name, num=num)

    @staticmethod
    def build(
        name: str,
        *points: tuple[int, int],
    ) -> BuildRoleCommand:
        return BuildRoleCommand(
            name=name,
            targetPos=_positions(points),
        )

    @staticmethod
    def remove(
        *points: tuple[int, int],
    ) -> RemoveRoleCommand:
        return RemoveRoleCommand(
            targetPos=_positions(points),
        )

    @staticmethod
    def accept_task() -> AcceptTaskRoleCommand:
        return AcceptTaskRoleCommand()

    @staticmethod
    def submit_answer(
        task_answer: str,
    ) -> SubmitAnswerRoleCommand:
        return SubmitAnswerRoleCommand(
            taskAnswer=task_answer,
        )

    @staticmethod
    def summon_treasure(
        *,
        points: tuple[tuple[int, int], ...],
        items: tuple[str, ...],
    ) -> SummonTreasureRoleCommand:
        return SummonTreasureRoleCommand(
            targetPos=_positions(points),
            item=items,
        )

    @staticmethod
    def use(
        name: str,
        *,
        points: tuple[tuple[int, int], ...] = (),
    ) -> UseRoleCommand:
        return UseRoleCommand(
            name=name,
            targetPos=(
                _positions(points)
                if points
                else None
            ),
        )

    @staticmethod
    def drop(
        name: str,
    ) -> DropRoleCommand:
        return DropRoleCommand(name=name)

    @staticmethod
    def collect(
        *points: tuple[int, int],
    ) -> CollectRoleCommand:
        return CollectRoleCommand(
            targetPos=_positions(points),
        )
