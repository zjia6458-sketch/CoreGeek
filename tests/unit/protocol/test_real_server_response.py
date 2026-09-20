import json
from pathlib import Path

from fortress_agent.protocol.codec import GameProtocolCodec


FIXTURE = (
    Path(__file__).parents[2]
    / "fixtures"
    / "server_round_85.json"
)


def load_fixture():
    return json.loads(
        FIXTURE.read_text(encoding="utf-8")
    )


def test_real_server_response_parses_to_normalized_game_state():
    result = GameProtocolCodec().parse_state(
        load_fixture()
    )

    assert result.ok, result
    state = result.value

    assert state.round_id == 85
    assert state.day == 1
    assert state.phase == "night"
    assert state.phase_round == 15
    assert state.turns_until_phase_change == 45

    assert state.team_type == "challenger"
    assert state.team_id == "6324"
    assert state.gold_self == 20
    assert state.score_self == 280

    assert len(state.characters) == 3
    assert {x.role for x in state.characters} == {
        "worker",
        "pioneer",
    }

    assert len(state.buildings) == 8
    assert len(state.enemies) == 4
    assert len(state.resources) == 6
    assert len(state.tasks) == 2

    boss = next(
        x
        for x in state.enemies
        if x.enemy_type == "bossrobot"
    )
    assert boss.attack == 40
    assert boss.score_value == 10
    assert boss.abnormal_state == "dizzy"

    assert state.market_prices["iron"] == 3
    assert state.weapon_shop["Bomb"] == 100

    assert "西部有一石门" in state.rumors[0]
    assert state.map_snapshot_complete is True
    assert state.server_errors[0].error_code == 2


def test_real_backpack_list_is_normalized_to_item_counts():
    result = GameProtocolCodec().parse_state(
        load_fixture()
    )
    assert result.ok

    worker = next(
        x
        for x in result.value.characters
        if x.actor_id == 10010
    )

    inventory = {
        x.item_type: x.amount
        for x in worker.inventory
    }

    assert inventory == {
        "copper": 1,
        "iron": 1,
        "stone": 1,
    }
