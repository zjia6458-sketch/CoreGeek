from fortress_agent.domain.state import Position
from fortress_agent.memory.world import WorldMemory
from fortress_agent.world.pathfinding import (
    AStarPathfinder,
    NavigationPolicy,
)


def test_astar_routes_around_known_wall():
    memory = WorldMemory()

    for x in range(5):
        for y in range(3):
            memory.map.observe(
                x=x,
                y=y,
                round_id=1,
                terrain="road",
            )

    memory.map.observe(
        x=2,
        y=1,
        round_id=1,
        terrain="wall",
    )

    result = AStarPathfinder(
        width=5,
        height=3,
    ).find_path(
        memory.view(),
        Position(0, 1),
        Position(4, 1),
        policy=NavigationPolicy.KNOWN_ONLY,
    )

    assert result.found
    assert Position(2, 1) not in result.path
    assert result.steps == 4


def test_known_only_rejects_unknown_corridor():
    memory = WorldMemory()

    memory.map.observe(
        x=0,
        y=0,
        round_id=1,
        terrain="road",
    )
    memory.map.observe(
        x=2,
        y=0,
        round_id=1,
        terrain="road",
    )

    result = AStarPathfinder(
        width=3,
        height=1,
    ).find_path(
        memory.view(),
        Position(0, 0),
        Position(2, 0),
        policy=NavigationPolicy.KNOWN_ONLY,
    )

    assert not result.found


def test_allow_unknown_can_cross_unknown_corridor():
    memory = WorldMemory()

    result = AStarPathfinder(
        width=3,
        height=1,
    ).find_path(
        memory.view(),
        Position(0, 0),
        Position(2, 0),
        policy=NavigationPolicy.ALLOW_UNKNOWN,
    )

    assert result.found
    assert result.steps == 2


def test_find_path_to_any_uses_multi_goal_semantics():
    """多个可交互终点应返回其中代价最低者，而不是依赖 goals 输入顺序。"""
    from fortress_agent.world.pathfinding import AStarPathfinder
    from fortress_agent.domain.state import Position
    from fortress_agent.memory.world import WorldMemory

    memory = WorldMemory().view()
    path = AStarPathfinder(width=10, height=10).find_path_to_any(
        memory,
        Position(0, 0),
        (Position(9, 9), Position(2, 2), Position(7, 1)),
    )

    assert path.found
    assert path.path[-1] == Position(2, 2)
    assert path.steps == 2
