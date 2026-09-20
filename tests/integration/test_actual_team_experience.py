import asyncio

from fortress_agent.application.runtime import FortressAgentRuntime


def response(round_no, *, role_results=None):
    return {
        "roundNo": round_no,
        "mapInfo": {
            "width": 41,
            "height": 32,
            "zones": [],
        },
        "teamOur": {
            "type": "challenger",
            "teamId": "x",
            "teamName": "x",
            "goldNum": 0,
            "totalScore": 0,
            "playerTasks": [],
            "roles": [
                {
                    "id": 10010,
                    "pos": {"x": 5, "y": 23},
                    "roleType": "worker",
                    "health": 220,
                    "attackPower": 0,
                    "attackRange": 0,
                    "backPackCapability": 100,
                    "backpack": [],
                },
                {
                    "id": 10011,
                    "pos": {"x": 10, "y": 12},
                    "roleType": "pioneer",
                    "health": 200,
                    "attackPower": 0,
                    "attackRange": 0,
                    "backPackCapability": 40,
                    "backpack": [],
                },
            ],
        },
        "teamEnemy": {"roles": []},
        "robot": {"roles": []},
        "lastRoundRoleActionResults": (
            role_results or {}
        ),
        "errors": [],
    }


def test_runtime_records_each_actually_sent_role_decision():
    runtime = FortressAgentRuntime()

    first = asyncio.run(
        runtime.handle_turn(response(10))
    )
    assert first.ok

    records = runtime.experience_store.all()
    assert len(records) == 2
    assert {
        str(x.action.actor_id)
        for x in records
    } == {"10010", "10011"}

    second = asyncio.run(
        runtime.handle_turn(
            response(
                11,
                role_results={
                    "10010": True,
                    "10011": False,
                },
            )
        )
    )
    assert second.ok

    first_round_records = [
        x for x in runtime.experience_store.all()
        if x.round_id == 10
    ]

    outcomes = {
        str(x.action.actor_id):
        runtime.experience_store.outcome_for(
            x.decision_id
        )
        for x in first_round_records
    }

    assert outcomes["10010"].action_legal is True
    assert outcomes["10011"].action_legal is False
