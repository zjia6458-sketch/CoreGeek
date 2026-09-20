from fortress_agent.events.base import DomainEvent
from fortress_agent.events.bus import EventBus
from fortress_agent.events.world import CellObserved


def test_event_bus_delivers_typed_and_generic_subscribers():
    bus = EventBus()
    typed = []
    generic = []

    bus.subscribe(CellObserved, typed.append)
    bus.subscribe(DomainEvent, generic.append)

    event = CellObserved(
        event_id="e1",
        round_id=1,
        x=1,
        y=2,
        terrain="road",
    )
    bus.publish(event)

    assert typed == [event]
    assert generic == [event]
