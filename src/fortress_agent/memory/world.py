from __future__ import annotations

from .map import CellMemoryView, MapMemory
from .resources import ResourceMemory, ResourceMemoryView, ResourceNodeMemoryView


class WorldMemory:
    def __init__(self) -> None:
        self.map = MapMemory()
        self.resources = ResourceMemory()

    def view(self) -> "WorldMemoryView":
        return WorldMemoryView(self)


class WorldMemoryView:
    """Read-only facade exposed to policy code."""

    def __init__(self, memory: WorldMemory) -> None:
        self._memory = memory
        self.resources = ResourceMemoryView(memory.resources)

    def cell(self, x: int, y: int) -> CellMemoryView:
        return self._memory.map.cell(x, y)

    def frontier_cells(self) -> tuple[tuple[int, int], ...]:
        return self._memory.map.frontier_cells()

    def resource(self, resource_id) -> ResourceNodeMemoryView | None:
        return self._memory.resources.get(resource_id)

    def available_resources(
        self,
        resource_type: str | None = None,
    ) -> tuple[ResourceNodeMemoryView, ...]:
        return self._memory.resources.available(resource_type)
