from fortress_agent.llm.coordinator import StrategicLLMCoordinator
from fortress_agent.memory.strategic import StrategicMemory
from fortress_agent.protocol.codec import GameProtocolCodec
from fortress_agent.safety.llm_budget import LLMBudgetTracker


def state(round_no=10, legend="west gate"):
    result = GameProtocolCodec().parse_state({
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
            "roles": [],
        },
        "teamEnemy": {"roles": []},
        "robot": {"roles": []},
        "worldNews": {
            "officialNews": "",
            "folkLegends": legend,
        },
        "errors": [],
    })
    assert result.ok
    return result.value


def test_new_unresolved_lore_gets_one_budgeted_prompt():
    s = state()
    memory = StrategicMemory()
    memory.observe_lore(
        round_id=s.round_id,
        text=s.world_news.folk_legends,
    )

    budget = LLMBudgetTracker()
    coordinator = StrategicLLMCoordinator()

    request = coordinator.plan(
        state=s,
        memory=memory.view(),
        budget=budget,
    )

    assert request is not None
    assert "west gate" in request.prompt

    coordinator.mark_sent(request)
    budget.record_call(
        s,
        task_exempt=False,
    )

    assert coordinator.plan(
        state=s,
        memory=memory.view(),
        budget=budget,
    ) is None
