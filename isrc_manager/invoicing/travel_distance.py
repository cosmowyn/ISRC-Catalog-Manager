"""Opt-in route distance lookup for invoice travel line preparation."""

from __future__ import annotations

import json
from dataclasses import dataclass
from urllib.parse import urlencode
from urllib.request import Request, urlopen


@dataclass(frozen=True, slots=True)
class TravelDistanceResult:
    origin_label: str
    destination_label: str
    one_way_km: str


def _clean_text(value: object | None) -> str:
    return str(value or "").strip()


class TravelDistanceService:
    """Queries public geocoding/routing endpoints and returns decimal km text.

    This is deliberately isolated from the UI so the desktop app can keep travel
    cost math deterministic while the network lookup remains optional.
    """

    user_agent = "ISRC-Catalog-Manager/1.0"

    def estimate_one_way_km(
        self, origin_address: str, destination_address: str
    ) -> TravelDistanceResult:
        origin = self._geocode(origin_address)
        destination = self._geocode(destination_address)
        route = self._json_get(
            "https://router.project-osrm.org/route/v1/driving/"
            f"{origin['lon']},{origin['lat']};{destination['lon']},{destination['lat']}?"
            + urlencode({"overview": "false", "alternatives": "false", "steps": "false"})
        )
        routes = route.get("routes") if isinstance(route, dict) else None
        if not isinstance(routes, list) or not routes:
            raise ValueError("No route distance was returned by the routing service.")
        distance_meters = routes[0].get("distance") if isinstance(routes[0], dict) else None
        if distance_meters is None:
            raise ValueError("The routing service response did not contain a distance.")
        km = int(round(float(distance_meters) / 100.0))
        return TravelDistanceResult(
            origin_label=str(origin["label"]),
            destination_label=str(destination["label"]),
            one_way_km=f"{km // 10}.{km % 10}".rstrip("0").rstrip("."),
        )

    def _geocode(self, address: str) -> dict[str, str]:
        clean = _clean_text(address)
        if not clean:
            raise ValueError("Both travel addresses are required.")
        payload = self._json_get(
            "https://nominatim.openstreetmap.org/search?"
            + urlencode({"format": "jsonv2", "limit": "1", "q": clean})
        )
        if not isinstance(payload, list) or not payload:
            raise ValueError(f"No map result was found for {clean!r}.")
        first = payload[0]
        if not isinstance(first, dict) or "lat" not in first or "lon" not in first:
            raise ValueError(f"The map result for {clean!r} did not contain coordinates.")
        return {
            "lat": str(first["lat"]),
            "lon": str(first["lon"]),
            "label": str(first.get("display_name") or clean),
        }

    def _json_get(self, url: str) -> object:
        request = Request(
            url,
            headers={
                "Accept": "application/json",
                "User-Agent": self.user_agent,
            },
        )
        with urlopen(request, timeout=12) as response:
            data = response.read()
        return json.loads(data.decode("utf-8"))
