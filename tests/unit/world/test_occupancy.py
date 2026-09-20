from fortress_agent.domain.state import BuildingState, Position
from fortress_agent.world.occupancy import BuildingFootprintResolver


def test_station_uses_two_by_two_top_left_footprint():
    station = BuildingState(
        building_id=1,
        building_type="station",
        position=Position(10, 24),
        hp=1500,
        max_hp=None,
        owner="self",
        cooldown_remaining=0,
        footprint_width=2,
        footprint_height=2,
        footprint_anchor="top_left",
    )

    cells = set(
        BuildingFootprintResolver.cells(
            station,
            map_width=41,
            map_height=32,
        )
    )

    assert cells == {
        Position(10, 24),
        Position(11, 24),
        Position(10, 23),
        Position(11, 23),
    }
