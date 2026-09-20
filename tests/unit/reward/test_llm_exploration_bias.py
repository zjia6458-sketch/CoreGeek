from types import MappingProxyType

from fortress_agent.domain.action import ExploreAction
from fortress_agent.domain.policy_state import PolicyState
from fortress_agent.llm.parser import StrategicLLMResponseParser
from fortress_agent.memory.strategic import StrategicMemory
from fortress_agent.memory.world import WorldMemory
from fortress_agent.policy.context import PolicyContext
from fortress_agent.protocol.codec import GameProtocolCodec
from fortress_agent.reward.models import ExplorationRewardModel


class Deadline:
    def remaining(self):
        return 10
    def expired(self):
        return False


def test_west_exploration_objective_rewards_westward_action():
    parsed = GameProtocolCodec().parse_state({
        "round": 85,
        "day": 1,
        "phase": "day",
        "characters": [{
            "id": 1,
            "role": "pioneer",
            "hp": 200,
            "position": {"x": 10, "y": 12},
        }],
    })
    assert parsed.ok

    strategic = StrategicMemory()
    result = StrategicLLMResponseParser().parse({
        "schema_version": "1.0",
        "source_round": 85,
        "recommended_mode": "explore",
        "mode_strength": 0.8,
        "confidence": 0.7,
        "expires_after_rounds": 130,
        "claims": [],
        "objectives": [{
            "objective_type": "explore_region",
            "priority": 1.0,
            "description": "inspect west",
            "target_position": None,
            "target_region": "west",
            "required_items": [],
        }],
        "short_reason": "",
    })
    assert result.ok
    strategic.add_advisory(result.value)

    ctx = PolicyContext(
        state=parsed.value,
        world_memory=WorldMemory().view(),
        policy_state=PolicyState.create(),
        deadline=Deadline(),
        features=MappingProxyType({}),
        strategic_memory=strategic.view(),
    )

    model = ExplorationRewardModel()

    west = model.estimate(
        ctx,
        ExploreAction(
            actor_id=1,
            action_type="move",
            x=9,
            y=12,
        ),
    )
    east = model.estimate(
        ctx,
        ExploreAction(
            actor_id=1,
            action_type="move",
            x=11,
            y=12,
        ),
    )

    assert west.total > east.total
