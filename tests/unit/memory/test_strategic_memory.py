from fortress_agent.llm.parser import StrategicLLMResponseParser
from fortress_agent.memory.strategic import StrategicMemory


def advisory(round_no=85):
    result = StrategicLLMResponseParser().parse({
        "schema_version": "1.0",
        "source_round": round_no,
        "recommended_mode": "explore",
        "mode_strength": 0.8,
        "confidence": 0.7,
        "expires_after_rounds": 20,
        "claims": [],
        "objectives": [],
        "short_reason": "",
    })
    assert result.ok
    return result.value


def test_lore_is_deduplicated_but_last_seen_is_updated():
    memory = StrategicMemory()

    assert memory.observe_lore(
        round_id=10,
        text="  west   gate ",
    )
    assert not memory.observe_lore(
        round_id=12,
        text="west gate",
    )

    entries = memory.view().lore()

    assert len(entries) == 1
    assert entries[0].first_seen_round == 10
    assert entries[0].last_seen_round == 12


def test_expired_advisory_is_not_active():
    memory = StrategicMemory()
    memory.add_advisory(advisory(85))

    assert memory.view().active_advisory(100) is not None
    assert memory.view().active_advisory(106) is None
