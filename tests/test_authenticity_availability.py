from unittest import mock

from isrc_manager.authenticity import availability


def test_authenticity_dependency_status_reports_missing_optional_modules():
    availability.authenticity_dependency_status.cache_clear()

    def fake_import(module_name):
        if module_name in {"numpy", "soundfile"}:
            raise RuntimeError(f"{module_name} unavailable")
        return object()

    try:
        with mock.patch(
            "isrc_manager.authenticity.availability.import_module",
            side_effect=fake_import,
        ):
            status = availability.authenticity_dependency_status()
            message = availability.authenticity_unavailable_message()
    finally:
        availability.authenticity_dependency_status.cache_clear()

    assert status.available is False
    assert status.missing_modules == ("numpy", "soundfile")
    assert "'numpy'" in message
    assert "'soundfile'" in message
    assert "requirements.txt" in message
