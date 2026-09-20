from fortress_agent.safety.llm_budget import LLMBudgetTracker
from fortress_agent.protocol.codec import GameProtocolCodec


def state(round_no=1, *, phase_task="", errors=()):
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
        "phaseTask": phase_task,
        "errors": list(errors),
    })
    assert result.ok, result
    return result.value


def test_normal_llm_budget_is_three_calls_per_day():
    tracker = LLMBudgetTracker()
    s = state()

    for _ in range(3):
        assert tracker.can_call(s)
        tracker.record_call(s)

    assert not tracker.can_call(s)


def test_budget_resets_on_new_game_day():
    tracker = LLMBudgetTracker()
    day1 = state(1)

    for _ in range(3):
        tracker.record_call(day1)

    day2 = state(131)
    assert tracker.can_call(day2)
    assert tracker.view().remaining == 3


def test_active_task_calls_are_exempt():
    tracker = LLMBudgetTracker()
    s = state(
        1,
        phase_task="active self evolution task",
    )

    for _ in range(10):
        assert tracker.can_call(s)
        tracker.record_call(s)

    assert tracker.view().used_normal_calls == 0


def test_error_code_5_marks_normal_budget_exhausted():
    tracker = LLMBudgetTracker()
    s = state(
        1,
        errors=[{
            "errorCode": 5,
            "description": "quota",
        }],
    )

    tracker.observe_state(s)

    assert not tracker.can_call(
        s,
        task_exempt=False,
    )
