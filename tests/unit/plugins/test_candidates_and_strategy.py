from types import MappingProxyType

from fortress_agent.candidates.basic import (
    ExplorationCandidateGenerator,
    GatherCandidateGenerator,
)
from fortress_agent.domain.policy_state import PolicyState
from fortress_agent.memory.world import WorldMemory
from fortress_agent.policy.context import PolicyContext
from fortress_agent.policy.strategy import StrategyProfile
from fortress_agent.protocol.codec import GameProtocolCodec
from fortress_agent.strategies.basic import BasicStrategySelector


class Deadline:
    def remaining(self):
        return 10.0
    def expired(self):
        return False


def make_ctx(memory, **state_overrides):
    payload = {
        "round": 1,
        "day": 1,
        "phase": "day",
        "turns_until_night": 30,
        "characters": [{
            "id": 1,
            "role": "worker",
            "hp": 220,
            "position": {"x": 5, "y": 5},
            "backpack_capacity": 100,
        }],
    }
    payload.update(state_overrides)

    parsed = GameProtocolCodec().parse_state(payload)
    assert parsed.ok, parsed

    return PolicyContext(
        state=parsed.value,
        world_memory=memory.view(),
        policy_state=PolicyState(),
        deadline=Deadline(),
        features=MappingProxyType({}),
    )


def test_strategy_selects_economy_when_worker_is_adjacent_to_resource():
    memory = WorldMemory()
    memory.resources.discover(
        resource_id="iron-1",
        resource_type="iron",
        x=5,
        y=6,
        amount=100,
        round_id=1,
    )

    profile = BasicStrategySelector().select(
        make_ctx(memory)
    )

    assert profile.strategy_id == "gather"
    assert "gather" in profile.candidate_tags


def test_strategy_selects_explore_without_gatherable_resource():
    profile = BasicStrategySelector().select(
        make_ctx(WorldMemory())
    )

    assert profile.strategy_id == "explore"


def test_gather_generator_only_generates_adjacent_resource():
    memory = WorldMemory()
    memory.resources.discover(
        resource_id="here",
        resource_type="iron",
        x=5,
        y=6,
        amount=100,
        round_id=1,
    )
    memory.resources.discover(
        resource_id="far",
        resource_type="iron",
        x=8,
        y=8,
        amount=100,
        round_id=1,
    )

    ctx = make_ctx(memory)
    strategy = StrategyProfile(
        strategy_id="gather",
        candidate_tags=frozenset({"gather"}),
    )

    actions = GatherCandidateGenerator().generate(
        ctx,
        strategy,
    )

    assert len(actions) == 1
    assert actions[0].resource_id == "here"


def test_exploration_generator_produces_adjacent_moves_only():
    ctx = make_ctx(WorldMemory())
    strategy = StrategyProfile(
        strategy_id="explore",
        candidate_tags=frozenset({"explore"}),
    )

    actions = ExplorationCandidateGenerator().generate(
        ctx,
        strategy,
    )

    assert len(actions) == 8
    assert all(
        max(abs(action.x - 5), abs(action.y - 5)) == 1
        for action in actions
    )
