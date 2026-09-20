import asyncio

from fortress_agent.application.runtime import FortressAgentRuntime


def test_runtime_creates_experience_and_attaches_next_turn_outcome():
    runtime = FortressAgentRuntime()

    first = asyncio.run(
        runtime.handle_turn({
            "round": 1,
            "day": 1,
            "phase": "day",
            "my_score": 0,
            "characters": [{
                "id": 1,
                "role": "pioneer",
                "hp": 200,
                "position": {"x": 5, "y": 5},
            }],
        })
    )

    assert first.ok
    assert first.experience_id is not None

    second = asyncio.run(
        runtime.handle_turn({
            "round": 2,
            "day": 1,
            "phase": "day",
            "my_score": 2,
            "characters": [{
                "id": 1,
                "role": "pioneer",
                "hp": 200,
                "position": {"x": 5, "y": 6},
            }],
        })
    )

    assert second.ok

    records = runtime.experience_store.all()
    assert len(records) == 2

    first_outcome = (
        runtime.experience_store.outcome_for(
            records[0].decision_id
        )
    )

    assert first_outcome is not None
    assert first_outcome.reward.score == 2


def test_request_timeout_does_not_attach_action_outcomes():
    """上一 HTTP 响应超时时，不能把传输异常归因到角色动作。"""
    runtime = FortressAgentRuntime()

    first = asyncio.run(runtime.handle_turn({
        "roundNo": 24,
        "mapInfo": {"width": 41, "height": 32, "zones": []},
        "teamOur": {
            "type": "defender",
            "teamId": "4737",
            "teamName": "B",
            "goldNum": 75,
            "totalScore": 0,
            "playerTasks": [],
            "roles": [{
                "id": 20011,
                "pos": {"x": 5, "y": 5},
                "roleType": "pioneer",
                "health": 200,
                "attackPower": 0,
                "attackRange": 0,
                "backPackCapability": 40,
                "backpack": [],
            }],
        },
        "teamEnemy": {"roles": []},
        "robot": {"roles": []},
        "lastRoundRoleActionResults": {},
        "errors": [],
        "worldNews": {"officialNews": "", "folkLegends": ""},
    }))
    assert first.ok

    previous_records = tuple(runtime.experience_store.all())
    assert previous_records

    second = asyncio.run(runtime.handle_turn({
        "roundNo": 25,
        "mapInfo": {"width": 41, "height": 32, "zones": []},
        "teamOur": {
            "type": "defender",
            "teamId": "4737",
            "teamName": "B",
            "goldNum": 75,
            "totalScore": 0,
            "playerTasks": [],
            "roles": [{
                "id": 20011,
                "pos": {"x": 5, "y": 5},
                "roleType": "pioneer",
                "health": 200,
                "attackPower": 0,
                "attackRange": 0,
                "backPackCapability": 40,
                "backpack": [],
            }],
        },
        "teamEnemy": {"roles": []},
        "robot": {"roles": []},
        "lastRoundRoleActionResults": {},
        "errors": [{
            "errorCode": 1,
            "description": "com.hw.codecraft.engine.exceptions.JudgeException: [TIMEOUT] player(4737) request timeout",
        }],
        "worldNews": {"officialNews": "", "folkLegends": ""},
    }))
    assert second.ok

    for exp in previous_records:
        assert runtime.experience_store.outcome_for(exp.decision_id) is None
