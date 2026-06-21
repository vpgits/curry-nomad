"""The route optimizer is the headline "limit" demo, so it gets the most pointed tests:
it must be deterministic, and 2-opt must never make the nearest-neighbor tour worse.

No DB, no LLM — pure functions.
"""

from __future__ import annotations

from nora.operations import routing

# A deliberately zig-zag set: depot in Colombo, then stops jumping north↔south↔centre, so the
# "visit them as listed" (naive) tour is long and the optimizer has real work to do.
_POINTS = [
    (6.9344, 79.8428),  # 0: depot (Colombo warehouse)
    (9.6615, 80.0255),  # 1: Jaffna (far north)
    (6.0535, 80.2210),  # 2: Galle (far south)
    (7.2906, 80.6337),  # 3: Kandy (centre)
    (7.2086, 79.8358),  # 4: Negombo (near depot)
    (5.9549, 80.5550),  # 5: Matara (far south)
    (8.3114, 80.4037),  # 6: Anuradhapura (north-centre)
]


def test_plan_is_deterministic():
    a = routing.plan(_POINTS)
    b = routing.plan(_POINTS)
    assert a.order == b.order
    assert a.optimized_km == b.optimized_km
    assert a.naive_km == b.naive_km


def test_two_opt_never_worse_than_nearest_neighbor():
    # 2-opt only ever accepts improving moves, so this inequality is a hard guarantee.
    result = routing.plan(_POINTS)
    assert result.optimized_km <= result.nearest_km + 1e-9


def test_optimizer_beats_the_naive_order_on_zigzag_input():
    # For this jumbled input the solver should be strictly (and substantially) shorter — the
    # whole point: the unplanned guess wastes distance the agent can't see.
    result = routing.plan(_POINTS)
    assert result.optimized_km < result.naive_km
    assert result.improvement_pct > 0


def test_order_is_a_valid_permutation_starting_at_depot():
    result = routing.plan(_POINTS)
    assert result.order[0] == 0  # tour starts at the depot
    assert sorted(result.order) == list(range(len(_POINTS)))  # visits every node exactly once


def test_haversine_is_symmetric_and_zero_on_self():
    a, b = (6.93, 79.84), (7.29, 80.63)
    assert routing.haversine_km(a, a) == 0.0
    assert abs(routing.haversine_km(a, b) - routing.haversine_km(b, a)) < 1e-9


def test_degenerate_depot_only():
    result = routing.plan([(6.93, 79.84)])
    assert result.order == [0]
    assert result.optimized_km == 0.0
    assert result.naive_km == 0.0
