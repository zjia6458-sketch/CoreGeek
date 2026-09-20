import json
from pathlib import Path

from fortress_agent.protocol.codec import GameProtocolCodec
from fortress_agent.protocol.server_factory import ServerCommandFactory


FIXTURE = (
    Path(__file__).parents[2]
    / "fixtures"
    / "server_round_85.json"
)


def payload():
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    data["teamOur"]["playerTasks"][0]["timeoutRounds"] = 25
    data["teamOur"]["roles"][3]["cooldown"] = 2
    data["robot"]["roles"][0]["targetTeam"] = "challenger"
    return data


def test_new_official_fields_are_preserved():
    result = GameProtocolCodec().parse_state(payload())
    assert result.ok, result
    state = result.value

    assert state.tasks[0].timeout_rounds == 25

    rocket = next(
        x for x in state.buildings
        if x.building_type == "rocket"
    )
    assert rocket.cooldown_remaining == 2

    small = next(
        x for x in state.enemies
        if x.enemy_type == "smallrobot"
    )
    assert small.target_team == "challenger"


def test_current_round_errors_are_not_misreported_as_cumulative_anomalies():
    result = GameProtocolCodec().parse_state(payload())
    assert result.ok

    assert result.value.round_error_count == 1
    assert result.value.anomaly_count == 0


def test_sell_buy_num_defaults_to_one():
    assert ServerCommandFactory.sell("stone", 1).num == 1
    assert ServerCommandFactory.buy("Medicine", 1).num == 1
