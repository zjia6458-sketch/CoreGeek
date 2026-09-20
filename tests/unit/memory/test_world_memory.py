from fortress_agent.memory.resources import ResourceStatus
from fortress_agent.observation.memory_engine import WorldMemoryEngine
from fortress_agent.protocol.codec import GameProtocolCodec


def parse(payload):
    result = GameProtocolCodec().parse_state(payload)
    assert result.ok, result
    return result.value


def test_first_observation_discovers_cell_and_resource():
    engine = WorldMemoryEngine()

    state = parse({
        "round": 1,
        "day": 1,
        "phase": "day",
        "visible_cells": [{"x": 5, "y": 5, "terrain": "mine"}],
        "resources": [{
            "id": "iron-1",
            "type": "iron",
            "position": {"x": 5, "y": 5},
            "amount": 100,
        }],
    })

    engine.observe(state)
    memory = engine.view()

    assert memory.cell(5, 5).discovered is True
    assert memory.cell(5, 5).terrain == "mine"

    resource = memory.resource("iron-1")
    assert resource is not None
    assert resource.status is ResourceStatus.AVAILABLE
    assert resource.last_known_amount == 100


def test_missing_resource_is_not_depleted_when_cell_is_not_observed():
    engine = WorldMemoryEngine()

    engine.observe(parse({
        "round": 1,
        "day": 1,
        "phase": "day",
        "visible_cells": [{"x": 5, "y": 5}],
        "resources": [{
            "id": "iron-1",
            "type": "iron",
            "position": {"x": 5, "y": 5},
            "amount": 100,
        }],
    }))

    # Round 2 does not observe (5,5); absence from response is not evidence.
    events = engine.observe(parse({
        "round": 2,
        "day": 1,
        "phase": "day",
        "visible_cells": [{"x": 1, "y": 1}],
        "resources": [],
    }))

    assert all(type(event).__name__ != "ResourceDepleted" for event in events)
    assert engine.view().resource("iron-1").status is ResourceStatus.AVAILABLE


def test_missing_resource_is_depleted_when_exact_cell_is_observed():
    engine = WorldMemoryEngine()

    engine.observe(parse({
        "round": 1,
        "day": 1,
        "phase": "day",
        "visible_cells": [{"x": 5, "y": 5}],
        "resources": [{
            "id": "iron-1",
            "type": "iron",
            "position": {"x": 5, "y": 5},
            "amount": 100,
        }],
    }))

    events = engine.observe(parse({
        "round": 2,
        "day": 1,
        "phase": "day",
        "visible_cells": [{"x": 5, "y": 5}],
        "resources": [],
    }))

    assert any(type(event).__name__ == "ResourceDepleted" for event in events)

    node = engine.view().resource("iron-1")
    assert node.status is ResourceStatus.DEPLETED
    assert node.depleted_round == 2
    assert engine.view().available_resources() == ()


def test_depleted_resource_remains_in_memory():
    engine = WorldMemoryEngine()

    engine.observe(parse({
        "round": 1,
        "day": 1,
        "phase": "day",
        "resources": [{
            "id": "iron-1",
            "type": "iron",
            "position": {"x": 5, "y": 5},
            "amount": 0,
            "active": False,
        }],
    }))

    node = engine.view().resource("iron-1")
    assert node is not None
    assert node.status is ResourceStatus.DEPLETED
    assert node.last_known_amount == 0


def test_resource_can_reappear_after_depletion():
    engine = WorldMemoryEngine()

    engine.observe(parse({
        "round": 1,
        "day": 1,
        "phase": "day",
        "resources": [{
            "id": "iron-1",
            "type": "iron",
            "position": {"x": 5, "y": 5},
            "amount": 0,
            "active": False,
        }],
    }))

    events = engine.observe(parse({
        "round": 2,
        "day": 1,
        "phase": "day",
        "resources": [{
            "id": "iron-1",
            "type": "iron",
            "position": {"x": 5, "y": 5},
            "amount": 50,
            "active": True,
        }],
    }))

    assert any(type(event).__name__ == "ResourceReplenished" for event in events)
    assert engine.view().resource("iron-1").status is ResourceStatus.AVAILABLE
    assert engine.view().resource("iron-1").last_known_amount == 50


def test_character_position_is_marked_visited():
    engine = WorldMemoryEngine()

    engine.observe(parse({
        "round": 1,
        "day": 1,
        "phase": "day",
        "characters": [{
            "id": 7,
            "role": "worker",
            "hp": 220,
            "position": {"x": 2, "y": 3},
        }],
    }))

    cell = engine.view().cell(2, 3)
    assert cell.discovered is True
    assert cell.visited is True
    assert cell.visit_count == 1
