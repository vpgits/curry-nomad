"""A small, deterministic delivery-route optimizer — and the whole point of the exercise.

Routing is the headline "limit of agentic development." Asked to "plan the delivery route for
these stops," a language model will confidently emit a plausible order — but vehicle routing is
NP-hard (a TSP), the model can't prove its answer is good, and it usually isn't. So we don't ask
it to. We hand the stops to *this*: a real, deterministic algorithm the agent (in Phase 2) merely
*calls*.

The method is classic and intentionally legible (visibility of the mechanism > cleverness):

  1. **Distance matrix** — great-circle (haversine) distance between every pair of points.
  2. **Nearest-neighbor** — a greedy first tour from the depot.
  3. **2-opt** — local search that repeatedly un-crosses the tour (reverse a segment whenever it
     shortens the trip) until no improving move remains.

Everything is pure Python over lists/floats — no solver dependency, no ``random``, no wall-clock —
so the same stops always yield the same tour. We also report ``naive_km`` (visiting the stops in
the order they came in — "no planning at all"), which is the baseline Phase 2 contrasts the
solver against: *"the unplanned guess is X km; the solver does Y km."*
"""

from __future__ import annotations

import math
from dataclasses import dataclass

# Earth radius (km) and a nominal urban delivery speed (Colombo traffic) for the time estimate.
_EARTH_RADIUS_KM = 6371.0088
AVG_SPEED_KMH = 30.0
# Only accept a 2-opt move that helps by more than this, so float noise can't cause a
# nondeterministic flip between two essentially-equal tours.
_EPS = 1e-9

Point = tuple[float, float]  # (lat, lng) in degrees


@dataclass(frozen=True)
class OptimizerResult:
    """The optimizer's output. ``order`` is node indices into the input ``points`` list, depot
    (index 0) first, in visit order; the closed tour returns to the depot."""

    order: list[int]
    optimized_km: float
    nearest_km: float  # nearest-neighbor tour length, before 2-opt
    naive_km: float  # visiting stops in input order — the "no planning" baseline
    est_minutes: float
    improvement_pct: float  # how much shorter optimized is vs naive


def haversine_km(a: Point, b: Point) -> float:
    """Great-circle distance between two (lat, lng) points, in km. Pure + deterministic."""
    lat1, lng1 = math.radians(a[0]), math.radians(a[1])
    lat2, lng2 = math.radians(b[0]), math.radians(b[1])
    dlat, dlng = lat2 - lat1, lng2 - lng1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlng / 2) ** 2
    return 2 * _EARTH_RADIUS_KM * math.asin(math.sqrt(h))


def distance_matrix(points: list[Point]) -> list[list[float]]:
    """Symmetric N×N distance matrix over the points (index 0 is the depot)."""
    n = len(points)
    m = [[0.0] * n for _ in range(n)]
    for i in range(n):
        for j in range(i + 1, n):
            d = haversine_km(points[i], points[j])
            m[i][j] = m[j][i] = d
    return m


def tour_length(order: list[int], matrix: list[list[float]], *, return_to_depot: bool = True) -> float:
    """Length of visiting nodes in ``order``; optionally close the loop back to ``order[0]``."""
    total = sum(matrix[order[i]][order[i + 1]] for i in range(len(order) - 1))
    if return_to_depot and len(order) > 1:
        total += matrix[order[-1]][order[0]]
    return total


def naive_length(matrix: list[list[float]]) -> float:
    """Tour length visiting nodes in their INPUT order (0, 1, 2, …) — the unplanned baseline."""
    return tour_length(list(range(len(matrix))), matrix)


def nearest_neighbor(matrix: list[list[float]], start: int = 0) -> list[int]:
    """Greedy tour from ``start``: repeatedly hop to the nearest unvisited node. Ties break to
    the lowest index, so the result is fully deterministic."""
    n = len(matrix)
    unvisited = set(range(n))
    unvisited.discard(start)
    order = [start]
    current = start
    while unvisited:
        # min() is stable on the key, and we add the index as a tie-breaker for determinism.
        nxt = min(unvisited, key=lambda j: (matrix[current][j], j))
        order.append(nxt)
        unvisited.discard(nxt)
        current = nxt
    return order


def two_opt(order: list[int], matrix: list[list[float]]) -> list[int]:
    """Improve a tour by 2-opt: reverse the segment between positions i and k whenever doing so
    shortens the closed tour, repeating full passes until none helps. The depot (position 0) is
    held fixed. Scan order is fixed (i ascending, then k) and improvements use a strict epsilon,
    so the output is identical on every run."""
    best = list(order)
    n = len(best)
    if n < 4:  # nothing for 2-opt to uncross
        return best
    improved = True
    while improved:
        improved = False
        for i in range(1, n - 1):
            for k in range(i + 1, n):
                nxt = best[(k + 1) % n]  # wraps to the depot when k is the last stop
                # Δ = (new edges) − (old edges) from reversing best[i..k].
                delta = (
                    matrix[best[i - 1]][best[k]]
                    + matrix[best[i]][nxt]
                    - matrix[best[i - 1]][best[i]]
                    - matrix[best[k]][nxt]
                )
                if delta < -_EPS:
                    best[i : k + 1] = reversed(best[i : k + 1])
                    improved = True
    return best


def plan(points: list[Point]) -> OptimizerResult:
    """Plan a route over ``points`` (index 0 = depot, 1..N = stops). Returns the optimized visit
    order plus the optimized / nearest-neighbor / naive lengths and a time estimate."""
    n = len(points)
    if n < 2:
        # Just the depot, no stops — a degenerate but well-defined zero-length tour.
        return OptimizerResult([0], 0.0, 0.0, 0.0, 0.0, 0.0)

    matrix = distance_matrix(points)
    naive_km = naive_length(matrix)
    nn_order = nearest_neighbor(matrix, start=0)
    nearest_km = tour_length(nn_order, matrix)
    opt_order = two_opt(nn_order, matrix)
    optimized_km = tour_length(opt_order, matrix)
    est_minutes = optimized_km / AVG_SPEED_KMH * 60.0
    improvement_pct = (naive_km - optimized_km) / naive_km * 100.0 if naive_km > _EPS else 0.0
    return OptimizerResult(
        order=opt_order,
        optimized_km=optimized_km,
        nearest_km=nearest_km,
        naive_km=naive_km,
        est_minutes=est_minutes,
        improvement_pct=improvement_pct,
    )
