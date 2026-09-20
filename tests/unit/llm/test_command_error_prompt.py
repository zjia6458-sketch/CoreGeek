from fortress_agent.llm.prompt import StrategicPromptBuilder
from fortress_agent.protocol.codec import GameProtocolCodec


def test_strategic_prompt_contains_static_and_learned_movement_safety_rules():
    parsed = GameProtocolCodec().parse_state({
        "round": 16,
        "day": 1,
        "phase": "day",
    })
    assert parsed.ok

    rule = (
        "[COMMAND_ERROR] role 20011 wants MOVE to (23,14), but target is "
        "impassable terrain [defenderTaskPoint1] => NEVER MOVE to (23,14)"
    )

    prompt = StrategicPromptBuilder().build(
        parsed.value,
        learned_hard_rules=(rule,),
    )

    assert "Never recommend MOVE onto challengerTaskPoint*/defenderTaskPoint* cells" in prompt
    assert "COMMAND_ERROR" in prompt
    assert "NEVER MOVE to (23,14)" in prompt


def test_coordinator_can_trigger_one_safety_revision_without_new_lore():
    from fortress_agent.llm.coordinator import StrategicLLMCoordinator
    from fortress_agent.memory.strategic import StrategicMemory
    from fortress_agent.safety.llm_budget import LLMBudgetTracker

    parsed = GameProtocolCodec().parse_state({
        "round": 16,
        "day": 1,
        "phase": "day",
    })
    assert parsed.ok
    state = parsed.value

    coordinator = StrategicLLMCoordinator()
    budget = LLMBudgetTracker()
    budget.observe_state(state)

    request = coordinator.plan(
        state=state,
        memory=StrategicMemory().view(),
        budget=budget,
        learned_hard_rules=("NEVER MOVE to (23,14)",),
        safety_revision_key="20011:MOVE:23,14:defenderTaskPoint1",
    )
    assert request is not None
    assert request.lore_id.startswith("safety:")
    assert "NEVER MOVE to (23,14)" in request.prompt

    coordinator.mark_sent(request)
    second = coordinator.plan(
        state=state,
        memory=StrategicMemory().view(),
        budget=budget,
        learned_hard_rules=("NEVER MOVE to (23,14)",),
        safety_revision_key="20011:MOVE:23,14:defenderTaskPoint1",
    )
    assert second is None
