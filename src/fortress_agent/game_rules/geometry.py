from __future__ import annotations

from math import sqrt

from fortress_agent.domain.state import Position


def chebyshev_distance(a: Position | tuple[int, int], b: Position | tuple[int, int]) -> int:
    ax, ay = (a.x, a.y) if isinstance(a, Position) else a
    bx, by = (b.x, b.y) if isinstance(b, Position) else b
    return max(abs(int(ax) - int(bx)), abs(int(ay) - int(by)))


def is_adjacent8(a: Position | tuple[int, int], b: Position | tuple[int, int]) -> bool:
    return chebyshev_distance(a, b) == 1


def neighbors8(x: int, y: int) -> tuple[tuple[int, int], ...]:
    # Stable clockwise-ish order for deterministic tie-breaking.  Diagonal
    # movement is legal even between two orthogonally adjacent obstacles.
    return (
        (x, y + 1),
        (x + 1, y + 1),
        (x + 1, y),
        (x + 1, y - 1),
        (x, y - 1),
        (x - 1, y - 1),
        (x - 1, y),
        (x - 1, y + 1),
    )


def angle_within_90(origin: Position, a: Position, b: Position) -> bool:
    """Return whether the angle A-origin-B is <= 90 degrees.

    For non-zero vectors this is equivalent to a non-negative dot product.
    """
    ax, ay = a.x - origin.x, a.y - origin.y
    bx, by = b.x - origin.x, b.y - origin.y
    if (ax == 0 and ay == 0) or (bx == 0 and by == 0):
        return False
    return ax * bx + ay * by >= 0


def euclidean_distance(a: Position, b: Position) -> float:
    dx, dy = a.x - b.x, a.y - b.y
    return sqrt(dx * dx + dy * dy)
