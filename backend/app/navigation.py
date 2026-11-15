"""Navigation Agent — A* routes and travel estimates."""

from __future__ import annotations

from heapq import heappop, heappush

from .models import Position, RouteRequest, RouteResponse


def manhattan(a: Position, b: Position) -> int:
    return abs(a.x - b.x) + abs(a.y - b.y)


def plan_path(
    start: Position,
    goal: Position,
    width: int,
    height: int,
    obstacles: set[tuple[int, int]] | None = None,
) -> list[Position]:
    """Return a shortest grid path from start to goal, inclusive of both ends.

    Uses A* with 4-connected movement. When the goal is unreachable, returns [].
    If start == goal, returns [start].
    """
    blocked = obstacles or set()
    start_xy = (start.x, start.y)
    goal_xy = (goal.x, goal.y)

    if start_xy == goal_xy:
        return [Position(x=start.x, y=start.y)]

    if (
        not (0 <= start.x < width and 0 <= start.y < height)
        or not (0 <= goal.x < width and 0 <= goal.y < height)
        or start_xy in blocked
        or goal_xy in blocked
    ):
        return []

    open_heap: list[tuple[int, int, tuple[int, int]]] = []
    counter = 0
    heappush(open_heap, (manhattan(start, goal), counter, start_xy))
    came_from: dict[tuple[int, int], tuple[int, int] | None] = {start_xy: None}
    g_score: dict[tuple[int, int], int] = {start_xy: 0}

    while open_heap:
        _, _, current = heappop(open_heap)
        if current == goal_xy:
            return _reconstruct(came_from, current)

        cx, cy = current
        for nx, ny in ((cx + 1, cy), (cx - 1, cy), (cx, cy + 1), (cx, cy - 1)):
            if not (0 <= nx < width and 0 <= ny < height):
                continue
            neighbor = (nx, ny)
            if neighbor in blocked:
                continue
            tentative = g_score[current] + 1
            if tentative >= g_score.get(neighbor, 1_000_000):
                continue
            came_from[neighbor] = current
            g_score[neighbor] = tentative
            counter += 1
            f = tentative + abs(nx - goal.x) + abs(ny - goal.y)
            heappush(open_heap, (f, counter, neighbor))

    return []


def path_length(path: list[Position]) -> int:
    """Number of traversable edges in a path (cells - 1)."""
    return max(0, len(path) - 1)


def _reconstruct(
    came_from: dict[tuple[int, int], tuple[int, int] | None],
    current: tuple[int, int],
) -> list[Position]:
    nodes = [current]
    while came_from[current] is not None:
        current = came_from[current]  # type: ignore[assignment]
        nodes.append(current)
    nodes.reverse()
    return [Position(x=x, y=y) for x, y in nodes]


class NavigationAgent:
    """Deterministic routing agent with explicit request/response contracts."""

    name = "navigation_agent"

    def route(self, request: RouteRequest) -> RouteResponse:
        obstacles = {(o.x, o.y) for o in request.obstacles}
        path = plan_path(
            request.start,
            request.goal,
            request.grid.width,
            request.grid.height,
            obstacles,
        )
        if not path:
            return RouteResponse(
                reachable=False,
                reason="unreachable_field",
            )
        cells = path_length(path)
        travel_time = cells / request.travel_speed if request.travel_speed > 0 else float("inf")
        return RouteResponse(
            reachable=True,
            path=path,
            travel_cells=cells,
            travel_time=travel_time,
        )


navigation_agent = NavigationAgent()
