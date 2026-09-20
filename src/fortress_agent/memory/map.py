from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CellMemoryView:
    x: int
    y: int
    terrain: str | None
    discovered: bool
    visited: bool
    visit_count: int
    first_seen_round: int | None
    last_seen_round: int | None


class MapMemory:
    """Dense 41 x 32 map memory.

    Dense arrays are simpler and faster than dictionaries for only 1312 cells.
    """

    def __init__(self, width: int = 41, height: int = 32) -> None:
        self.width = width
        self.height = height
        size = width * height

        self._terrain: list[str | None] = [None] * size
        self._discovered = bytearray(size)
        self._visited = bytearray(size)
        self._visit_count: list[int] = [0] * size
        self._first_seen: list[int] = [-1] * size
        self._last_seen: list[int] = [-1] * size

    def _index(self, x: int, y: int) -> int:
        if not (0 <= x < self.width and 0 <= y < self.height):
            raise IndexError(f"cell out of bounds: ({x}, {y})")
        return y * self.width + x

    def observe(
        self,
        *,
        x: int,
        y: int,
        round_id: int,
        terrain: str | None,
    ) -> None:
        idx = self._index(x, y)

        if not self._discovered[idx]:
            self._first_seen[idx] = round_id

        self._discovered[idx] = 1
        self._last_seen[idx] = round_id

        # None means "not supplied", not "erase terrain knowledge".
        if terrain is not None:
            self._terrain[idx] = terrain

    def visit(self, *, x: int, y: int, round_id: int) -> None:
        idx = self._index(x, y)
        self.observe(x=x, y=y, round_id=round_id, terrain=None)
        self._visited[idx] = 1
        self._visit_count[idx] += 1

    def cell(self, x: int, y: int) -> CellMemoryView:
        idx = self._index(x, y)
        first_seen = self._first_seen[idx]
        last_seen = self._last_seen[idx]

        return CellMemoryView(
            x=x,
            y=y,
            terrain=self._terrain[idx],
            discovered=bool(self._discovered[idx]),
            visited=bool(self._visited[idx]),
            visit_count=self._visit_count[idx],
            first_seen_round=None if first_seen < 0 else first_seen,
            last_seen_round=None if last_seen < 0 else last_seen,
        )


    def export_state(self) -> dict[str, object]:
        return {
            "width": self.width,
            "height": self.height,
            "terrain": list(self._terrain),
            "discovered": list(self._discovered),
            "visited": list(self._visited),
            "visit_count": list(self._visit_count),
            "first_seen": list(self._first_seen),
            "last_seen": list(self._last_seen),
        }

    def import_state(self, state: dict[str, object]) -> None:
        width = int(state["width"])
        height = int(state["height"])

        if width != self.width or height != self.height:
            raise ValueError(
                f"snapshot map size {width}x{height} does not match "
                f"{self.width}x{self.height}"
            )

        size = self.width * self.height

        terrain = list(state["terrain"])
        discovered = list(state["discovered"])
        visited = list(state["visited"])
        visit_count = list(state["visit_count"])
        first_seen = list(state["first_seen"])
        last_seen = list(state["last_seen"])

        if not all(
            len(values) == size
            for values in (
                terrain,
                discovered,
                visited,
                visit_count,
                first_seen,
                last_seen,
            )
        ):
            raise ValueError("invalid map snapshot length")

        self._terrain = [None if x is None else str(x) for x in terrain]
        self._discovered = bytearray(int(x) for x in discovered)
        self._visited = bytearray(int(x) for x in visited)
        self._visit_count = [int(x) for x in visit_count]
        self._first_seen = [int(x) for x in first_seen]
        self._last_seen = [int(x) for x in last_seen]

    def frontier_cells(self) -> tuple[tuple[int, int], ...]:
        result: list[tuple[int, int]] = []
        for y in range(self.height):
            for x in range(self.width):
                if not self.cell(x, y).discovered:
                    continue
                is_frontier = False
                for dx in (-1, 0, 1):
                    for dy in (-1, 0, 1):
                        if dx == 0 and dy == 0:
                            continue
                        nx, ny = x + dx, y + dy
                        if 0 <= nx < self.width and 0 <= ny < self.height and not self.cell(nx, ny).discovered:
                            is_frontier = True
                            break
                    if is_frontier:
                        break
                if is_frontier:
                    result.append((x, y))
        return tuple(result)
