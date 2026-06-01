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
