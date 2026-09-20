import asyncio

from fortress_agent.application.bootstrap import build_logged_runtime
from fortress_agent.memory.resources import ResourceStatus


def payload(round_no: int, *, include_resource: bool):
    return {
        "roundNo": round_no,
        "mapInfo": {
            "width": 41,
            "height": 32,
            "zones": (
                [{"neutralType": "stone", "pos": {"x": 5, "y": 5}}]
                if include_resource
                else []
            ),
        },
        "teamOur": {
            "type": "challenger",
            "teamId": "recover",
            "teamName": "Recover",
            "goldNum": 0,
            "totalScore": 0,
            "playerTasks": [],
            "roles": [{
                "id": 10010,
                "pos": {"x": 5, "y": 5},
                "roleType": "worker",
                "health": 220,
                "attackPower": 0,
                "attackRange": 0,
                "backPackCapability": 100,
                "backpack": [],
            }],
        },
        "teamEnemy": {"roles": []},
        "robot": {"roles": []},
        "worldNews": {"officialNews": "", "folkLegends": ""},
        "errors": [],
    }


def test_world_memory_recovers_from_snapshot_and_event_log(tmp_path):
    first = build_logged_runtime(tmp_path)
    result = asyncio.run(first.handle_turn(payload(10, include_resource=True)))
    assert result.ok
    first.close()

    second = build_logged_runtime(tmp_path)

    recovered = second.world_memory.resource("zone:stone:5:5")
    assert recovered is not None
    assert recovered.status is ResourceStatus.AVAILABLE
    assert second.world_memory.cell(5, 5).visited

    result2 = asyncio.run(second.handle_turn(payload(11, include_resource=False)))
    assert result2.ok

    depleted = second.world_memory.resource("zone:stone:5:5")
    assert depleted is not None
    assert depleted.status is ResourceStatus.DEPLETED

    second.close()
