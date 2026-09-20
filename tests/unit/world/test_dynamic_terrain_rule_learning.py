from dataclasses import dataclass

from fortress_agent.domain.action import MoveAction
from fortress_agent.memory.feedback import RuntimeFeedbackMemory
from fortress_agent.memory.world import WorldMemory
from fortress_agent.protocol.codec import GameProtocolCodec
from fortress_agent.world.traversability import TraversabilityMap


@dataclass(frozen=True)
class Exp:
    action: MoveAction


def parse_state(round_no, *, zones, result=None, description=""):
    parsed = GameProtocolCodec().parse_state({
        "roundNo": round_no,
        "mapInfo": {
            "width": 41,
            "height": 32,
            "zones": [
                {"neutralType": terrain, "pos": {"x": x, "y": y}}
                for terrain, x, y in zones
            ],
        },
        "teamOur": {
            "type": "defender",
            "teamId": "x",
            "teamName": "x",
            "goldNum": 0,
            "totalScore": 0,
            "playerTasks": [],
            "roles": [{
                "id": 20011,
                "pos": {"x": 4, "y": 4},
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
            {} if result is None else {"20011": result}
        ),
        "errors": (
            [] if not description else [{
                "errorCode": 4,
                "description": description,
            }]
        ),
    })
    assert parsed.ok
    return parsed.value


def test_impassable_feedback_learns_terrain_type_not_coordinate():
    memory = RuntimeFeedbackMemory(generic_retry_ban_rounds=1)
    failed = MoveAction(actor_id=20011, action_type="move", x=5, y=4)
    description = (
        "role 20011 wants MOVE to (5,4), but target is "
        "impassable terrain [mysteryGate]"
    )

    feedback_state = parse_state(
        10,
        zones=[("mysteryGate", 5, 4)],
        result=False,
        description=description,
    )
    record = memory.observe(
        feedback_state,
        previous_experiences=(Exp(failed),),
    )

    assert len(record.new_terrain_rules) == 1
    rule = record.new_terrain_rules[0]
    assert rule.terrain_type == "mysteryGate"
    assert rule.signature == "terrain:mysterygate:traversability=impassable"
    assert memory.view().is_terrain_impassable("MYSTERYGATE")
    assert memory.view().impassable_cells() == ()


def test_learned_terrain_rule_generalizes_to_different_coordinates():
    memory = RuntimeFeedbackMemory(generic_retry_ban_rounds=1)
    failed = MoveAction(actor_id=20011, action_type="move", x=5, y=4)
    description = (
        "role 20011 wants MOVE to (5,4), but target is "
        "impassable terrain [mysteryGate]"
    )
    memory.observe(
        parse_state(
            10,
            zones=[("mysteryGate", 5, 4)],
            result=False,
            description=description,
        ),
        previous_experiences=(Exp(failed),),
    )

    later = parse_state(
        20,
        zones=[
            ("road", 5, 4),
            ("mysteryGate", 30, 9),
            ("mysteryGate", 31, 9),
        ],
    )
    traversal = TraversabilityMap.from_state_and_memory(
        later,
        WorldMemory().view(),
        memory.view(),
    )

    # Original coordinate is no longer permanently blocked merely because it
    # exposed the failure. The semantic terrain type is the learned rule key.
    assert traversal.is_walkable(5, 4)
    assert not traversal.is_walkable(30, 9)
    assert not traversal.is_walkable(31, 9)
    assert traversal.block_reason(30, 9) == "learned_impassable_terrain:mysteryGate"


def test_failed_move_still_has_short_exact_retry_suppression():
    memory = RuntimeFeedbackMemory(generic_retry_ban_rounds=2)
    failed = MoveAction(actor_id=20011, action_type="move", x=5, y=4)
    memory.observe(
        parse_state(10, zones=[], result=False),
        previous_experiences=(Exp(failed),),
    )

    # The short MOVE retry ban is team-wide: once one role spends an
    # anomaly discovering a bad target, no other role may immediately try it.
    assert memory.view().is_move_retry_blocked(20011, 5, 4, 10)
    assert memory.view().is_move_retry_blocked(20010, 5, 4, 10)
    assert memory.view().is_move_retry_blocked(20012, 5, 4, 12)
    assert not memory.view().is_move_retry_blocked(20011, 5, 4, 13)
    assert not memory.view().is_move_retry_blocked(20010, 5, 4, 13)
