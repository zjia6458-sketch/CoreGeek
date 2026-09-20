from dataclasses import dataclass

from fortress_agent.domain.action import MoveAction
from fortress_agent.memory.feedback import RuntimeFeedbackMemory
from fortress_agent.protocol.codec import GameProtocolCodec


@dataclass(frozen=True)
class Exp:
    action: MoveAction


def state(*, description="", legal=False, last_cmd_result=""):
    parsed = GameProtocolCodec().parse_state({
        "roundNo": 16,
        "mapInfo": {
            "width": 41,
            "height": 32,
            "zones": [{
                "neutralType": "defenderTaskPoint1",
                "pos": {"x": 23, "y": 14},
            }],
        },
        "teamOur": {
            "type": "defender",
            "teamId": "4737",
            "teamName": "B",
            "goldNum": 0,
            "totalScore": 0,
            "playerTasks": [],
            "roles": [{
                "id": 20011,
                "pos": {"x": 23, "y": 13},
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
        "lastRoundRoleActionResults": {"20011": legal},
        "errors": ([{"errorCode": 4, "description": description}] if description else []),
        "lastCmdResult": last_cmd_result,
    })
    assert parsed.ok
    return parsed.value


def test_command_error_parses_impassable_target_into_hard_memory_rule():
    memory = RuntimeFeedbackMemory()
    raw = (
        "[COMMAND_ERROR] role 20011 wants MOVE to (23,14), "
        "but target is impassable terrain [defenderTaskPoint1]"
    )

    record = memory.observe(
        state(description=raw),
        previous_experiences=(
            Exp(MoveAction(actor_id=20011, action_type="move", x=23, y=14)),
        ),
    )

    view = memory.view()
    assert len(record.command_errors) == 1
    assert len(record.new_safety_lessons) == 1
    assert view.is_terrain_impassable("defenderTaskPoint1")
    assert view.impassable_cells() == ()
    assert "terrain type [defenderTaskPoint1] is IMPASSABLE" in view.hard_rules()[0]
    assert "ANY neutral-zone cell" in view.hard_rules()[0]


def test_false_role_result_alone_temporarily_suppresses_exact_move_retry():
    memory = RuntimeFeedbackMemory()
    action = MoveAction(actor_id=20011, action_type="move", x=23, y=14)
    memory.observe(
        state(description="", legal=False),
        previous_experiences=(Exp(action),),
    )

    # Boolean failure alone is authoritative for exact retry suppression but
    # is insufficient evidence for a permanent terrain/cell ban.
    assert memory.view().is_action_forbidden(action, current_round=16)
    assert memory.view().is_move_retry_blocked(20010, 23, 14, 16)
    assert memory.view().is_move_retry_blocked(20012, 23, 14, 16)
    assert not memory.view().is_terrain_impassable("defenderTaskPoint1")


def test_server_error_description_without_command_error_prefix_is_parsed():
    memory = RuntimeFeedbackMemory()
    raw = (
        "role 20011 wants MOVE to (23,14), "
        "but target is impassable terrain [defenderTaskPoint1]"
    )

    record = memory.observe(
        state(description=raw, legal=False),
        previous_experiences=(
            Exp(MoveAction(actor_id=20011, action_type="move", x=23, y=14)),
        ),
    )

    assert len(record.command_errors) == 1
    lesson = record.command_errors[0]
    assert lesson.terrain == "defenderTaskPoint1"
    assert lesson.source == "server_error"
    assert memory.view().is_terrain_impassable("defenderTaskPoint1")
    assert memory.view().impassable_cells() == ()


def test_role_result_false_is_primary_failure_trigger_without_error_text():
    memory = RuntimeFeedbackMemory(generic_retry_ban_rounds=3)
    action = MoveAction(actor_id=20011, action_type="move", x=22, y=13)

    record = memory.observe(
        state(description="", legal=False),
        previous_experiences=(Exp(action),),
    )

    assert len(record.action_failures) == 1
    failure = record.action_failures[0]
    assert failure.role_id == "20011"
    assert failure.reason == "role_action_result_false"
    assert failure.source == "role_action_result"
    assert memory.view().is_action_forbidden(action, current_round=16)
    assert memory.view().is_action_forbidden(action, current_round=19)
    assert not memory.view().is_action_forbidden(action, current_round=20)



def test_semantic_server_error_does_not_learn_without_failed_role_result():
    memory = RuntimeFeedbackMemory()
    raw = (
        "role 20011 wants MOVE to (23,14), "
        "but target is impassable terrain [defenderTaskPoint1]"
    )

    record = memory.observe(
        state(description=raw, legal=True),
        previous_experiences=(
            Exp(MoveAction(actor_id=20011, action_type="move", x=23, y=14)),
        ),
    )

    assert record.action_failures == ()
    assert record.command_errors == ()
    assert record.new_safety_lessons == ()
    assert not memory.view().is_terrain_impassable("defenderTaskPoint1")
    assert memory.view().impassable_cells() == ()


def test_semantic_server_error_must_match_actual_previous_target():
    memory = RuntimeFeedbackMemory()
    raw = (
        "role 20011 wants MOVE to (23,14), "
        "but target is impassable terrain [defenderTaskPoint1]"
    )
    actual = MoveAction(actor_id=20011, action_type="move", x=22, y=13)

    record = memory.observe(
        state(description=raw, legal=False),
        previous_experiences=(Exp(actual),),
    )

    # The boolean failure still closes the loop for the action we actually sent.
    assert len(record.action_failures) == 1
    assert record.action_failures[0].reason == "role_action_result_false"
    assert memory.view().is_action_forbidden(actual, current_round=16)

    # The unrelated/mismatched text cannot poison permanent traversability.
    assert record.command_errors == ()
    assert record.new_safety_lessons == ()
    assert not memory.view().is_terrain_impassable("defenderTaskPoint1")
    assert memory.view().impassable_cells() == ()


def test_last_cmd_result_is_recorded_but_never_parsed_as_role_move_error():
    memory = RuntimeFeedbackMemory()
    fake_text = (
        "role 20011 wants MOVE to (23,14), "
        "but target is impassable terrain [defenderTaskPoint1]"
    )
    actual = MoveAction(actor_id=20011, action_type="move", x=22, y=13)

    record = memory.observe(
        state(
            description="",
            legal=False,
            last_cmd_result=fake_text,
        ),
        previous_experiences=(Exp(actual),),
    )

    assert record.command_result == fake_text
    assert record.command_errors == ()
    assert record.action_failures[0].reason == "role_action_result_false"
    assert memory.view().impassable_cells() == ()
