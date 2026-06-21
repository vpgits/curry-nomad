"""Fixed geography for delivery routing — shared by the seed and the services.

Hand-picked, approximate (lat, lng) centroids for the cities Curry Nomad delivers to, plus the
Colombo warehouse depot every route starts and ends at. Kept as a plain constant (not a DB
table) so the seed and ``create_order``/``plan_route`` read the *same* deterministic coordinates,
and so the routing demo has real geometry without an extra moving part.

Only Sri Lankan cities get delivery routes; the export cities are here for completeness (export
orders ship by freight, not the local van) and are not seeded as pending local deliveries.
"""

from __future__ import annotations

Point = tuple[float, float]

# The depot: Curry Nomad's packing warehouse in Colombo. Every route is a loop from here.
DEPOT: Point = (6.9344, 79.8428)

# City -> (lat, lng). Local cities first (these get routed), then export hubs.
CITY_COORDS: dict[str, Point] = {
    # --- Sri Lanka (local delivery network) ---
    "Colombo": (6.9271, 79.8612),
    "Dehiwala": (6.8512, 79.8653),
    "Moratuwa": (6.7730, 79.8816),
    "Negombo": (7.2086, 79.8358),
    "Gampaha": (7.0917, 79.9999),
    "Kandy": (7.2906, 80.6337),
    "Galle": (6.0535, 80.2210),
    "Matara": (5.9549, 80.5550),
    "Kurunegala": (7.4863, 80.3647),
    "Anuradhapura": (8.3114, 80.4037),
    "Jaffna": (9.6615, 80.0255),
    # --- Export hubs (not locally routed) ---
    "London": (51.5074, -0.1278),
    "Toronto": (43.6532, -79.3832),
    "Sydney": (-33.8688, 151.2093),
    "Dubai": (25.2048, 55.2708),
    "Melbourne": (-37.8136, 144.9631),
}

# The cities the local delivery van actually serves (a route is only ever planned over these).
LOCAL_CITIES: tuple[str, ...] = (
    "Colombo",
    "Dehiwala",
    "Moratuwa",
    "Negombo",
    "Gampaha",
    "Kandy",
    "Galle",
    "Matara",
    "Kurunegala",
    "Anuradhapura",
    "Jaffna",
)


def coords_for_city(city: str) -> Point:
    """Return the (lat, lng) for a city, defaulting to the Colombo depot if unknown."""
    return CITY_COORDS.get(city, DEPOT)
