import json
from dataclasses import replace
from types import MappingProxyType

from fortress_agent.candidates.basic import AttackCandidateGenerator, MoveCandidateGenerator
from fortress_agent.candidates.business import SellCandidateGenerator
from fortress_agent.candidates.navigation import WallBuildApproachCandidateGenerator, WeaponBuildApproachCandidateGenerator, DefensePostCandidateGenerator
from fortress_agent.domain.policy_state import PolicyState
from fortress_agent.domain.auxiliary import ExecuteCommandDecision
from fortress_agent.memory.world import WorldMemory
from fortress_agent.policy.context import PolicyContext
from fortress_agent.policy.strategy import StrategyProfile
from fortress_agent.protocol.codec import GameProtocolCodec
from fortress_agent.tasks.session import TaskSessionCoordinator


class Deadline:
    def remaining(self):
        return 10.0
    def expired(self):
        return False


def _ctx(state):
    return PolicyContext(
        state=state,
        world_memory=WorldMemory().view(),
        policy_state=PolicyState.create(),
        deadline=Deadline(),
        features=MappingProxyType({}),
    )


def _role(role_id, x, y, role_type, *, backpack=None, level=None, cooldown=0, attack_range=0, attack_power=0):
    return {
        "id": role_id,
        "pos": {"x": x, "y": y},
        "roleType": role_type,
        "health": 220 if role_type == "worker" else 200 if role_type == "pioneer" else 1000,
        "attackPower": attack_power,
        "attackRange": attack_range,
        "backPackCapability": 100 if role_type == "worker" else 40 if role_type == "pioneer" else 0,
        "backpack": backpack or [],
        "level": level,
        "cooldown": cooldown,
    }


def _state(*, round_no=10, phase_task="", score=0, roles=None, zones=None, robots=None, tasks=None, gold=0):
    parsed = GameProtocolCodec().parse_state({
        "roundNo": round_no,
        "mapInfo": {"width": 41, "height": 32, "zones": zones or []},
        "teamOur": {
            "type": "challenger", "teamId": "x", "teamName": "x",
            "goldNum": gold, "totalScore": score,
            "playerTasks": tasks or [], "roles": roles or [],
        },
        "teamEnemy": {"roles": []},
        "robot": {"roles": robots or []},
        "phaseTask": phase_task,
        "lastCmdResult": "",
        "llmResp": "",
        "worldNews": {"officialNews": "", "folkLegends": ""},
        "vendorShopList": [{"name": "stone", "price": 1}, {"name": "iron", "price": 2}],
        "weaponShopList": [],
        "errors": [],
    })
    assert parsed.ok, parsed
    return parsed.value


def _base_and_rockets(worker_backpack=None):
    return [
        _role(10010, 5, 5, "worker", backpack=worker_backpack or []),
        _role(10011, 13, 15, "pioneer"),
        _role(10012, 6, 6, "worker"),
        {**_role(10013, 9, 22, "station", level=1), "health": 1500},
        _role(10040, 8, 22, "rocket", level=1, attack_range=10, attack_power=20),
        _role(10041, 8, 21, "rocket", level=1, attack_range=10, attack_power=20),
        _role(10042, 8, 20, "rocket", level=1, attack_range=10, attack_power=20),
    ]


def test_active_task_pioneer_has_no_generic_move_candidates():
    state = _state(
        phase_task="active",
        roles=[_role(10011, 13, 15, "pioneer")],
        zones=[{"neutralType": "challengerTaskPoint1", "pos": {"x": 14, "y": 14}}],
    )
    actions = MoveCandidateGenerator().generate(
        _ctx(state), StrategyProfile(strategy_id="active_task", candidate_tags=frozenset({"move"}))
    )
    assert not [a for a in actions if str(a.actor_id) == "10011"]


def test_stone_is_reserved_after_three_weapons_until_walls_complete():
    roles = _base_and_rockets(["stone", "stone", "stone"])
    state = _state(
        roles=roles,
        zones=[{"neutralType": "vendor", "pos": {"x": 5, "y": 4}}],
        gold=0,
    )
    actions = SellCandidateGenerator().generate(
        _ctx(state), StrategyProfile(strategy_id="economy", candidate_tags=frozenset({"sell"}))
    )
    assert not [a for a in actions if a.name.lower() == "stone"]


def test_worker_with_stone_returns_to_wall_build_ring_after_three_weapons():
    state = _state(roles=_base_and_rockets(["stone", "stone", "stone", "stone"]), gold=0)
    actions = WallBuildApproachCandidateGenerator().generate(
        _ctx(state), StrategyProfile(strategy_id="economy", candidate_tags=frozenset({"build"}))
    )
    assert actions
    assert all(a.goal_kind == "wall_build" for a in actions)


def test_rocket_aoe_can_target_empty_cluster_center():
    roles = [
        _role(10010, 9, 10, "worker"),
        _role(10040, 10, 10, "rocket", level=1, attack_range=10, attack_power=20),
    ]
    robots = []
    for i, (x, y) in enumerate(((15, 14), (14, 15), (16, 15), (15, 16)), start=1):
        robots.append({
            "id": 30000 + i, "pos": {"x": x, "y": y}, "roleType": "smallRobot",
            "health": 10, "abnormalState": "", "targetTeam": "challenger",
        })
    state = _state(round_no=85, roles=roles, robots=robots)
    actions = AttackCandidateGenerator().generate(
        _ctx(state), StrategyProfile(strategy_id="defense", candidate_tags=frozenset({"defense"}))
    )
    assert actions
    assert actions[0].targets == (type(actions[0].targets[0])(15, 15),)
    assert (15, 15) not in {(r["pos"]["x"], r["pos"]["y"]) for r in robots}


def test_task_skill_memory_is_reused_as_sop_context_after_scored_task():
    coordinator = TaskSessionCoordinator()
    state1 = _state(
        round_no=10,
        phase_task="task A",
        score=0,
        roles=[_role(10011, 13, 15, "pioneer")],
        zones=[{"neutralType": "challengerTaskPoint1", "pos": {"x": 14, "y": 14}}],
    )
    first = coordinator.plan(state1)
    assert first and first.execute_cmd
    coordinator.record_dispatched(ExecuteCommandDecision(
        decision_id="t10:execute", decision_type="execute_cmd", source_round=10,
        source_node="task_session", purpose="test", command=first.execute_cmd,
        task_session_id=first.session_id,
    ))

    ended = replace(state1, round_id=11, phase_task="", score_self=20.0)
    assert coordinator.plan(ended) is None

    state2 = replace(state1, round_id=12, phase_task="task B", score_self=20.0)
    second = coordinator.plan(state2)
    assert second is not None
    assert second.prior_skill_available
    assert "同类型任务历史成功命令" in second.prompt
    assert "find /tmp/selfEvolutionTask" in second.prompt


def test_defense_post_uses_only_pioneer_common_rocket_controller_when_robots_exist():
    roles = [
        _role(10010, 2, 2, "worker"),
        _role(10011, 3, 2, "pioneer"),
        _role(10012, 4, 2, "worker"),
        {**_role(10013, 9, 22, "station", level=1), "health": 1500},
        _role(10040, 9, 20, "rocket", level=1, attack_range=10, attack_power=20),
        _role(10041, 8, 20, "rocket", level=1, attack_range=10, attack_power=20),
        _role(10042, 8, 22, "rocket", level=1, attack_range=10, attack_power=20),
    ]
    robots = [{
        "id": 30001, "pos": {"x": 35, "y": 5}, "roleType": "smallRobot",
        "health": 40, "abnormalState": "", "targetTeam": "challenger",
    }]
    state = _state(round_no=85, roles=roles, robots=robots)
    actions = DefensePostCandidateGenerator().generate(
        _ctx(state), StrategyProfile(strategy_id="defense", candidate_tags=frozenset({"defense"}))
    )
    assert len(actions) == 1
    assert str(actions[0].actor_id) == "10011"
    assert actions[0].goal_id == "rocket_cluster_controller"


def test_active_task_strategy_keeps_worker_economy_tags():
    from fortress_agent.strategies.reference import build_reference_strategy_selector
    state = _state(
        phase_task="active",
        roles=[
            _role(10010, 5, 5, "worker"),
            _role(10011, 13, 15, "pioneer"),
            _role(10012, 6, 6, "worker"),
        ],
        zones=[{"neutralType": "challengerTaskPoint1", "pos": {"x": 14, "y": 14}}],
    )
    strategy = build_reference_strategy_selector().select(_ctx(state))
    assert strategy.strategy_id == "active_task"
    assert {"task", "gather", "sell", "build"}.issubset(strategy.candidate_tags)


def test_primary_builder_returns_to_weapon_ring_before_three_towers():
    roles = [
        _role(10010, 2, 2, "worker"),
        _role(10011, 13, 15, "pioneer"),
        _role(10012, 4, 4, "worker"),
        {**_role(10013, 9, 22, "station", level=1), "health": 1500},
    ]
    state = _state(roles=roles, gold=50)
    actions = WeaponBuildApproachCandidateGenerator().generate(
        _ctx(state), StrategyProfile(strategy_id="economy", candidate_tags=frozenset({"build"}))
    )
    assert actions
    assert {str(a.actor_id) for a in actions} == {"10010"}
    assert all(a.goal_kind == "weapon_build" for a in actions)


def test_new_task_rejects_stale_task_llm_response_from_older_round():
    coordinator = TaskSessionCoordinator()
    state = _state(
        round_no=20,
        phase_task="new task",
        roles=[_role(10011, 13, 15, "pioneer")],
        zones=[{"neutralType": "challengerTaskPoint1", "pos": {"x": 14, "y": 14}}],
    )
    stale = json.dumps({
        "schema_version": "task-1.0",
        "source_round": 10,
        "action": "execute",
        "execute_cmd": "echo SHOULD_NOT_RUN",
        "task_answer": "",
        "confidence": 1.0,
        "short_reason": "old task",
    })
    plan = coordinator.plan(replace(state, raw_llm_response=stale))
    assert plan is not None
    assert "SHOULD_NOT_RUN" not in plan.execute_cmd


def test_gatling_ballistic_hits_nearest_robot_on_same_center_line():
    from fortress_agent.domain.state import Position
    from fortress_agent.game_rules.combat import estimate_attack_value
    roles = [_role(10020, 10, 10, "gatling", level=1, attack_range=3, attack_power=10)]
    robots = [
        {"id": 30001, "pos": {"x": 11, "y": 11}, "roleType": "smallRobot", "health": 10, "abnormalState": "", "targetTeam": "challenger"},
        {"id": 30002, "pos": {"x": 13, "y": 13}, "roleType": "smallRobot", "health": 10, "abnormalState": "", "targetTeam": "challenger"},
    ]
    state = _state(round_no=85, roles=roles, robots=robots)
    weapon = state.buildings[0]
    score, _ = estimate_attack_value(state, weapon, (Position(13, 13),))
    assert score == 1.0


def test_railgun_energy_penetrates_in_distance_order_and_depletes():
    from fortress_agent.domain.state import Position
    from fortress_agent.game_rules.combat import estimate_attack_value
    roles = [_role(10030, 10, 10, "railgun", level=2, attack_range=8, attack_power=20)]
    robots = [
        {"id": 30001, "pos": {"x": 11, "y": 10}, "roleType": "smallRobot", "health": 10, "abnormalState": "", "targetTeam": "challenger"},
        {"id": 30002, "pos": {"x": 12, "y": 10}, "roleType": "smallRobot", "health": 15, "abnormalState": "", "targetTeam": "challenger"},
        {"id": 30003, "pos": {"x": 13, "y": 10}, "roleType": "smallRobot", "health": 10, "abnormalState": "", "targetTeam": "challenger"},
    ]
    state = _state(round_no=85, roles=roles, robots=robots)
    weapon = state.buildings[0]
    score, survival = estimate_attack_value(state, weapon, (Position(13, 10),))
    assert score == 1.0
    assert survival > 0
