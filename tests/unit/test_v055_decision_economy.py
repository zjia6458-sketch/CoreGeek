import asyncio
import json
from dataclasses import replace
from types import MappingProxyType

from fortress_agent.application.bootstrap import build_runtime
from fortress_agent.candidates.basic import GatherCandidateGenerator, ResourceApproachCandidateGenerator
from fortress_agent.candidates.navigation import WallBuildApproachCandidateGenerator
from fortress_agent.domain.auxiliary import ExecuteCommandDecision
from fortress_agent.domain.policy_state import PolicyState
from fortress_agent.game_rules.economy import wall_target_for_day, stone_batch_target
from fortress_agent.memory.world import WorldMemory
from fortress_agent.policy.context import PolicyContext
from fortress_agent.policy.strategy import StrategyProfile
from fortress_agent.protocol.codec import GameProtocolCodec
from fortress_agent.tasks.session import TaskSessionCoordinator


class Deadline:
    def remaining(self): return 10.0
    def expired(self): return False


def role(rid,x,y,typ,backpack=None,level=None):
    return {"id":rid,"pos":{"x":x,"y":y},"roleType":typ,"health":220 if typ=="worker" else 200,
            "attackPower":0,"attackRange":10 if typ=="rocket" else 0,
            "backPackCapability":100 if typ=="worker" else 40 if typ=="pioneer" else 0,
            "backpack":backpack or [],"level":level,"cooldown":0}


def state(round_no=20, *, backpack=None, walls=0, phase_task=""):
    roles=[role(10010,9,14,"worker",backpack=backpack),role(10011,13,15,"pioneer"),role(10012,10,14,"worker")]
    roles += [{**role(10013,9,22,"station",level=1),"health":1500}]
    for i,pos in enumerate(((8,22),(8,21),(8,20))):
        roles.append(role(10040+i,*pos,"rocket",level=1))
    for i in range(walls):
        roles.append(role(10100+i,7+i%4,19-(i//4),"wall",level=1))
    parsed=GameProtocolCodec().parse_state({
        "roundNo":round_no,"mapInfo":{"width":41,"height":32,"zones":[
            {"neutralType":"stone","pos":{"x":9,"y":13}},
            {"neutralType":"copper","pos":{"x":5,"y":28}},
            {"neutralType":"challengerTaskPoint1","pos":{"x":14,"y":14}},
        ]},
        "teamOur":{"type":"challenger","teamId":"x","teamName":"x","goldNum":0,"totalScore":0,"playerTasks":[],"roles":roles},
        "teamEnemy":{"roles":[]},"robot":{"roles":[]},"phaseTask":phase_task,
        "lastCmdResult":"","llmResp":"","worldNews":{"officialNews":"","folkLegends":""},
        "vendorShopList":[{"name":"stone","price":1},{"name":"copper","price":3}],"weaponShopList":[],"errors":[]})
    assert parsed.ok
    return parsed.value


def ctx(s):
    mem=WorldMemory()
    # 直接由 runtime memory engine 更新更复杂；测试只需要候选，手工注册资源。
    mem.resources.discover(resource_id="zone:stone:9:13", resource_type="stone", x=9, y=13, amount=10, round_id=20)
    mem.resources.discover(resource_id="zone:copper:5:28", resource_type="copper", x=5, y=28, amount=10, round_id=20)
    return PolicyContext(state=s,world_memory=mem.view(),policy_state=PolicyState.create(),deadline=Deadline(),features=MappingProxyType({}))


def test_standard_station_uses_full_sixteen_cell_three_side_wall_blueprint():
    assert wall_target_for_day(state(round_no=20)) == 16
    assert wall_target_for_day(state(round_no=150)) == 16


def test_worker_collects_stone_until_batch_then_returns_to_build():
    s=state(round_no=25,backpack=["stone","stone","stone"])
    c=ctx(s)
    profile=StrategyProfile(strategy_id="economy",candidate_tags=frozenset({"gather","build"}))
    gathers=GatherCandidateGenerator().generate(c,profile)
    assert any(str(a.actor_id)=="10010" and "stone" in a.resource_id for a in gathers)
    assert WallBuildApproachCandidateGenerator().generate(c,profile)==()

    s4=state(round_no=26,backpack=["stone"]*4)
    c4=ctx(s4)
    approaches=WallBuildApproachCandidateGenerator().generate(c4,profile)
    assert any(str(a.actor_id)=="10010" for a in approaches)
    resource_moves=ResourceApproachCandidateGenerator().generate(c4,profile)
    assert not any(str(a.actor_id)=="10010" for a in resource_moves)


def test_auxiliary_execute_decision_gets_next_round_outcome():
    def payload(r,last="",llm=""):
        return {
          "roundNo":r,"mapInfo":{"width":41,"height":32,"zones":[{"neutralType":"challengerTaskPoint1","pos":{"x":14,"y":14}}]},
          "teamOur":{"type":"challenger","teamId":"x","teamName":"x","goldNum":50,"totalScore":0,"playerTasks":[],"roles":[role(10011,13,15,"pioneer")]},
          "teamEnemy":{"roles":[]},"robot":{"roles":[]},"phaseTask":"task","lastCmdResult":last,"llmResp":llm,
          "worldNews":{"officialNews":"","folkLegends":""},"vendorShopList":[],"weaponShopList":[],"errors":[]}
    runtime=build_runtime(log_mode="low")
    r1=asyncio.run(runtime.handle_turn(payload(10)))
    assert json.loads(r1.response_json)["executeCmd"]
    records=runtime.auxiliary_experience_store.all()
    execute=[x for x in records if isinstance(x.decision,ExecuteCommandDecision)]
    assert execute
    asyncio.run(runtime.handle_turn(payload(11,last="[exitCode:0]\nOK")))
    outcome=runtime.auxiliary_experience_store.outcome_for(execute[-1].decision_id)
    assert outcome is not None
    assert outcome.transport_success is True
    assert "OK" in outcome.result_text


def test_task_session_only_learns_dispatched_commands():
    coord=TaskSessionCoordinator()
    s=state(round_no=10,phase_task="task")
    plan=coord.plan(s)
    assert plan and plan.execute_cmd
    ended=replace(s,round_id=11,phase_task="",score_self=20.0)
    coord.plan(ended)
    # 未调用 record_dispatched，因此不能把计划但未确认发送的命令当成成功 SOP。
    s2=replace(s,round_id=12,phase_task="task2",score_self=20.0)
    assert not coord.plan(s2).prior_skill_available


def test_both_workers_prioritize_stone_while_day1_wall_target_unmet():
    s=state(round_no=30,backpack=[])
    c=ctx(s)
    profile=StrategyProfile(strategy_id="economy",candidate_tags=frozenset({"gather"}))
    gathers=GatherCandidateGenerator().generate(c,profile)
    by_actor={}
    for action in gathers:
        by_actor.setdefault(str(action.actor_id), []).append(action)
    assert {"10010","10012"}.issubset(by_actor)
    assert all("stone" in a.resource_id for a in by_actor["10010"])
    assert all("stone" in a.resource_id for a in by_actor["10012"])


def test_wall_reserve_window_uses_backpack_threshold_instead_of_single_stone():
    # 距夜 22 回合属于施工预留窗口，但 1/100 的矿物占比远低于默认 35%，
    # 不应该为了 1 块 stone 立刻往返。
    s=state(round_no=48,backpack=["stone"])
    c=ctx(s)
    profile=StrategyProfile(strategy_id="prepare",candidate_tags=frozenset({"build","prepare"}))
    assert WallBuildApproachCandidateGenerator().generate(c,profile) == ()

    # 达到配置比例后开始返场施工。
    s_loaded=state(round_no=48,backpack=["stone"]*35)
    c_loaded=ctx(s_loaded)
    approaches=WallBuildApproachCandidateGenerator().generate(c_loaded,profile)
    assert any(str(a.actor_id)=="10010" for a in approaches)
