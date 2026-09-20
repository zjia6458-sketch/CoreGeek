from dataclasses import dataclass

from fortress_agent.domain.action import MoveAction
from fortress_agent.memory.feedback import (
    RULE_SCOPE_GLOBAL,
    RULE_SCOPE_RESOURCE,
    RULE_SCOPE_TASK,
    RULE_STATUS_ACTIVE,
    RULE_STATUS_DORMANT,
    RULE_STATUS_RETIRED,
    RuntimeFeedbackMemory,
)
from fortress_agent.memory.world import WorldMemory
from fortress_agent.protocol.codec import GameProtocolCodec
from fortress_agent.world.traversability import TraversabilityMap


@dataclass(frozen=True)
class Exp:
    action: MoveAction


def make_state(
    round_no: int,
    *,
    terrain: str | None,
    pos=(5, 4),
    role_result=None,
    error_text="",
    task_valid: bool | None = None,
):
    zones = []
    if terrain is not None:
        zones.append({
            "neutralType": terrain,
            "pos": {"x": pos[0], "y": pos[1]},
        })

    tasks = []
    if task_valid is not None:
        tasks.append({
            "taskType": "自进化类1",
            "taskPosition": {"x": pos[0], "y": pos[1]},
            "coldDownRounds": 0,
            "scoreReward": 10,
            "goldReward": 0,
            "isValid": task_valid,
            "timeoutRounds": 20,
        })

    raw = {
        "roundNo": round_no,
        "mapInfo": {
            "width": 41,
            "height": 32,
            "zones": zones,
        },
        "teamOur": {
            "type": "defender",
            "teamId": "x",
            "teamName": "x",
            "goldNum": 0,
            "totalScore": 0,
            "playerTasks": tasks,
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
        "lastRoundRoleActionResults": (
            {} if role_result is None else {"20011": role_result}
        ),
        "errors": (
            [] if not error_text else [{
                "errorCode": 4,
                "description": error_text,
            }]
        ),
    }
    parsed = GameProtocolCodec().parse_state(raw)
    assert parsed.ok
    return parsed.value


def learn_rule(memory, *, terrain, round_no=10, pos=(5, 4), task_valid=None):
    action = MoveAction(
        actor_id=20011,
        action_type="move",
        x=pos[0],
        y=pos[1],
    )
    error = (
        f"role 20011 wants MOVE to ({pos[0]},{pos[1]}), but target is "
        f"impassable terrain [{terrain}]"
    )
    record = memory.observe(
        make_state(
            round_no,
            terrain=terrain,
            pos=pos,
            role_result=False,
            error_text=error,
            task_valid=task_valid,
        ),
        previous_experiences=(Exp(action),),
    )
    assert len(record.new_terrain_rules) == 1
    return record.new_terrain_rules[0]


def test_resource_rule_dormant_when_resource_disappears_and_reactivates():
    memory = RuntimeFeedbackMemory()
    rule = learn_rule(memory, terrain="stone")
    assert rule.scope == RULE_SCOPE_RESOURCE
    assert rule.status == RULE_STATUS_ACTIVE
    assert memory.view().is_terrain_impassable("stone")

    gone = memory.observe(
        make_state(11, terrain=None),
        previous_experiences=(),
    )
    assert len(gone.terrain_rule_transitions) == 1
    transition = gone.terrain_rule_transitions[0]
    assert transition.from_status == RULE_STATUS_ACTIVE
    assert transition.to_status == RULE_STATUS_DORMANT
    assert transition.reason == "resource_type_absent_from_complete_snapshot"
    assert not memory.view().is_terrain_impassable("stone")

    back = memory.observe(
        make_state(12, terrain="stone"),
        previous_experiences=(),
    )
    assert len(back.terrain_rule_transitions) == 1
    assert back.terrain_rule_transitions[0].to_status == RULE_STATUS_ACTIVE
    assert memory.view().is_terrain_impassable("stone")


def test_taskpoint_rule_is_global_and_physical_point_stays_blocked_when_task_invalid():
    memory = RuntimeFeedbackMemory()
    rule = learn_rule(
        memory,
        terrain="defenderTaskPoint1",
        pos=(23, 14),
        task_valid=True,
    )
    # Official rules: the four TaskPoint map elements always block movement;
    # only task content/availability changes.
    assert rule.scope == RULE_SCOPE_GLOBAL
    assert rule.status == RULE_STATUS_ACTIVE

    invalid_state = make_state(
        11,
        terrain="defenderTaskPoint1",
        pos=(23, 14),
        task_valid=False,
    )
    invalid_record = memory.observe(invalid_state, previous_experiences=())
    assert invalid_record.terrain_rule_transitions == ()
    assert memory.view().is_terrain_impassable("defenderTaskPoint1")

    traversal = TraversabilityMap.from_state_and_memory(
        invalid_state,
        WorldMemory().view(),
        memory.view(),
    )
    assert not traversal.is_walkable(23, 14)


def test_global_terrain_rule_does_not_dormant_merely_because_absent():
    memory = RuntimeFeedbackMemory()
    rule = learn_rule(memory, terrain="mysteryGate")
    assert rule.scope == RULE_SCOPE_GLOBAL

    record = memory.observe(
        make_state(11, terrain=None),
        previous_experiences=(),
    )
    assert record.terrain_rule_transitions == ()
    assert memory.view().is_terrain_impassable("mysteryGate")


def test_successful_move_is_counterevidence_and_retires_impassable_rule():
    memory = RuntimeFeedbackMemory()
    learn_rule(memory, terrain="mysteryGate", pos=(5, 4))
    assert memory.view().is_terrain_impassable("mysteryGate")

    successful = MoveAction(
        actor_id=20011,
        action_type="move",
        x=5,
        y=4,
    )
    record = memory.observe(
        make_state(
            11,
            terrain="mysteryGate",
            pos=(5, 4),
            role_result=True,
        ),
        previous_experiences=(Exp(successful),),
    )
    assert len(record.terrain_rule_transitions) == 1
    transition = record.terrain_rule_transitions[0]
    assert transition.to_status == RULE_STATUS_RETIRED
    assert transition.reason == "successful_move_counterevidence"
    assert not memory.view().is_terrain_impassable("mysteryGate")
    assert memory.view().terrain_rules()[0].status == RULE_STATUS_RETIRED
