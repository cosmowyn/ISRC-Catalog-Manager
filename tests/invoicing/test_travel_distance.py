import pytest

from isrc_manager.invoicing import travel_distance
from isrc_manager.invoicing.travel_distance import TravelDistanceService


def test_travel_distance_service_returns_one_decimal_km_from_route_response(monkeypatch):
    service = TravelDistanceService()
    calls: list[str] = []
    responses = iter(
        [
            [{"lat": "52.1", "lon": "4.3", "display_name": "Origin"}],
            [{"lat": "52.2", "lon": "5.1", "display_name": "Destination"}],
            {"routes": [{"distance": 12_345}]},
        ]
    )

    def fake_json_get(url: str):
        calls.append(url)
        return next(responses)

    monkeypatch.setattr(service, "_json_get", fake_json_get)

    result = service.estimate_one_way_km("Origin address", "Destination address")

    assert result.origin_label == "Origin"
    assert result.destination_label == "Destination"
    assert result.one_way_km == "12.3"
    assert "nominatim.openstreetmap.org" in calls[0]
    assert "router.project-osrm.org" in calls[2]


def test_travel_distance_service_validates_missing_addresses():
    service = TravelDistanceService()

    try:
        service.estimate_one_way_km("", "Destination")
    except ValueError as exc:
        assert "addresses" in str(exc)
    else:  # pragma: no cover - defensive assertion guard
        raise AssertionError("Expected a missing-address validation error.")


def test_travel_distance_service_rejects_empty_or_malformed_api_responses(monkeypatch):
    service = TravelDistanceService()
    monkeypatch.setattr(
        service, "_geocode", lambda address: {"lat": "52", "lon": "5", "label": address}
    )

    monkeypatch.setattr(service, "_json_get", lambda _url: {"routes": []})
    with pytest.raises(ValueError, match="No route distance"):
        service.estimate_one_way_km("A", "B")

    monkeypatch.setattr(service, "_json_get", lambda _url: {"routes": [{}]})
    with pytest.raises(ValueError, match="did not contain a distance"):
        service.estimate_one_way_km("A", "B")

    geocode_service = TravelDistanceService()
    monkeypatch.setattr(geocode_service, "_json_get", lambda _url: [])
    with pytest.raises(ValueError, match="No map result"):
        geocode_service._geocode("Nowhere")

    monkeypatch.setattr(geocode_service, "_json_get", lambda _url: [{"display_name": "Incomplete"}])
    with pytest.raises(ValueError, match="did not contain coordinates"):
        geocode_service._geocode("Incomplete")


def test_travel_distance_json_get_sends_headers_and_decodes_response(monkeypatch):
    captured = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return b'{"ok": true}'

    def fake_urlopen(request, *, timeout):
        captured["url"] = request.full_url
        captured["headers"] = dict(request.headers)
        captured["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr(travel_distance, "urlopen", fake_urlopen)

    payload = TravelDistanceService()._json_get("https://example.test/route")

    assert payload == {"ok": True}
    assert captured["url"] == "https://example.test/route"
    assert captured["timeout"] == 12
    assert captured["headers"]["Accept"] == "application/json"
    assert captured["headers"]["User-agent"] == TravelDistanceService.user_agent
