import asyncio
import json

from fortress_agent.application.runtime import FortressAgentRuntime


def request(round_no, *, pos, error="", action_result=None):
    return {
        "roundNo": round_no,
        "mapInfo": {"width": 41, "height": 32, "zones": []},
        "teamOur": {
            "type": "defender", "teamId": "4737", "teamName": "B",
            "goldNum": 0, "totalScore": 0, "playerTasks": [],
            "roles": [{
                "id": 20011,
                "pos": {"x": pos[0], "y": pos[1]},
                "roleType": "pioneer", "health": 200,
                "attackPower": 0, "attackRange": 0,
                "backPackCapability": 40, "backpack": [],
            }],
        },
        "teamEnemy": {"roles": []}, "robot": {"roles": []},
        "lastRoundRoleActionResults": (
            {} if action_result is None else {"20011": action_result}
        ),
        "errors": ([{"errorCode": 4, "description": error}] if error else []),
    }


def test_command_error_detail_is_attached_to_experience_outcome():
    runtime = FortressAgentRuntime()
    first = asyncio.run(runtime.handle_turn(request(1, pos=(5, 5))))
    assert first.ok
    first_wire = json.loads(first.response_json)
    first_command = first_wire["roleCommandMap"]["20011"]
    assert first_command["action"] == "move"
    target = first_command["targetPos"][0]

    error = (
        f"role 20011 wants MOVE to ({target['x']},{target['y']}), "
        "but target is impassable terrain [unknownRock]"
    )
    second = asyncio.run(runtime.handle_turn(
        request(2, pos=(5, 5), error=error, action_result=False)
    ))
    assert second.ok

    outcomes = [
        runtime.experience_store.outcome_for(exp.decision_id)
        for exp in runtime.experience_store.all()
        if exp.round_id == 1
    ]
    outcomes = [x for x in outcomes if x is not None]
    assert outcomes
    assert any(4 in outcome.server_error_codes for outcome in outcomes)
    assert any(error in outcome.server_error_messages for outcome in outcomes)
    assert any(outcome.command_error_signatures for outcome in outcomes)
