from fortress_agent.memory.map import MapMemory


def test_frontier_is_discovered_cell_adjacent_to_unknown_cell():
    memory = MapMemory(width=4, height=4)

    memory.observe(x=1, y=1, round_id=1, terrain="road")
    memory.observe(x=1, y=2, round_id=1, terrain="road")

    frontiers = set(memory.frontier_cells())

    assert (1, 1) in frontiers
    assert (1, 2) in frontiers


def test_fully_surrounded_discovered_cell_is_not_frontier():
    memory = MapMemory(width=3, height=3)

    for y in range(3):
        for x in range(3):
            memory.observe(x=x, y=y, round_id=1, terrain="road")

    assert memory.frontier_cells() == ()
