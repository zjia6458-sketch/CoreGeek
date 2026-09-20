"""Short per-role position history used to discourage A-B-A oscillation."""
from __future__ import annotations

from collections import defaultdict, deque


class MovementHistoryView:
    def __init__(self, memory: "MovementHistoryMemory") -> None:
        self._memory = memory

    def backtrack_penalty(self, actor_id, x: int, y: int) -> float:
        history = self._memory._positions.get(str(actor_id))
        if not history or len(history) < 2:
            return 0.0
        target = (int(x), int(y))
        # The strongest loop signal is A -> B -> A. A smaller recent-position
        # penalty also breaks longer deterministic cycles without making a
        # necessary retreat illegal.
        if target == history[-2]:
            return 4.0
        return 0.75 if target in tuple(history)[:-1] else 0.0


class MovementHistoryMemory:
    def __init__(self, max_positions: int = 8) -> None:
        self._positions = defaultdict(lambda: deque(maxlen=max(3, int(max_positions))))

    def observe(self, state) -> None:
        for actor in state.characters:
            if actor.hp <= 0:
                continue
            key = str(actor.actor_id)
            position = (int(actor.position.x), int(actor.position.y))
            history = self._positions[key]
            if not history or history[-1] != position:
                history.append(position)

    def view(self) -> MovementHistoryView:
        return MovementHistoryView(self)
