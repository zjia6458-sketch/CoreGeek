from types import MappingProxyType

from fortress_agent.domain.policy_state import PolicyState
from fortress_agent.memory.world import WorldMemory
from fortress_agent.policy.context import PolicyContext
from fortress_agent.policy.strategy import StrategyProfile
from fortress_agent.policy.team import TeamPlanner
from fortress_agent.protocol.codec import GameProtocolCodec


class Deadline:
    def remaining(self): return 10
    def expired(self): return False


class FailingSelector:
    def select(self, ctx):
        raise AssertionError("selector must not be called when strategy is supplied")


class EmptyCandidates:
    def generate(self, ctx, strategy): return ()


class PassLegal:
    def filter(self, ctx, actions): return actions


class PassRules:
    def apply(self, ctx, actions): return actions, (), ()


class EmptyRanker:
    def select(self, ctx, actions, strategy): return None


def test_team_planner_reuses_policy_graph_strategy_without_second_selection():
    parsed = GameProtocolCodec().parse_state({
        "round": 1,
        "day": 1,
        "phase": "day",
    })
    assert parsed.ok

    ctx = PolicyContext(
        state=parsed.value,
        world_memory=WorldMemory().view(),
        policy_state=PolicyState.create(),
        deadline=Deadline(),
        features=MappingProxyType({}),
    )

    planner = TeamPlanner(
        strategy_selector=FailingSelector(),
        candidate_service=EmptyCandidates(),
        legal_filter=PassLegal(),
        rule_engine=PassRules(),
        ranker=EmptyRanker(),
    )

    strategy = StrategyProfile(
        strategy_id="already_selected",
        candidate_tags=frozenset(),
    )

    result = planner.plan(ctx, strategy=strategy)
    assert result.decisions == ()
