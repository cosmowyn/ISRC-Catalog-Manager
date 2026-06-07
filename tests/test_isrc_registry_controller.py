from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from PySide6.QtCore import QDate

from isrc_manager import isrc_registry_controller as registry_controller
from isrc_manager.isrc_registry import ISRCRegistryConflict


class _Field:
    def __init__(self):
        self.text = ""
        self.placeholder = ""
        self.tooltip = ""
        self.cleared = 0

    def clear(self) -> None:
        self.cleared += 1
        self.text = ""

    def setText(self, text: str) -> None:
        self.text = text

    def setPlaceholderText(self, text: str) -> None:
        self.placeholder = text

    def setToolTip(self, text: str) -> None:
        self.tooltip = text


class _Toggle:
    def __init__(self, checked: bool):
        self._checked = checked
        self.enabled = None

    def isChecked(self) -> bool:
        return self._checked

    def setEnabled(self, enabled: bool) -> None:
        self.enabled = bool(enabled)


def _conflict(**overrides) -> ISRCRegistryConflict:
    values = {
        "isrc_compact": "NLABC2601001",
        "isrc_iso": "NL-ABC-26-01001",
        "profile_path": "/profiles/demo.sqlite",
        "profile_name": "Demo",
        "track_id": 12,
        "track_title": "Claimed Song",
        "claim_kind": "generated",
        "claim_status": "active",
    }
    values.update(overrides)
    return ISRCRegistryConflict(**values)


def test_profile_paths_are_deduplicated_and_registry_sync_logs_conflicts(tmp_path):
    profile_one = tmp_path / "one.sqlite"
    profile_two = tmp_path / "two.sqlite"
    summary = SimpleNamespace(profile_count=2, conflict_count=1)
    registry = SimpleNamespace(sync_profiles=mock.Mock(return_value=summary))
    app = SimpleNamespace(
        profile_store=SimpleNamespace(
            list_profiles=mock.Mock(return_value=[profile_one, profile_one, profile_two])
        ),
        current_db_path=str(profile_two),
        application_isrc_registry=registry,
        _profile_paths_for_isrc_registry=lambda: registry_controller._profile_paths_for_isrc_registry(
            app
        ),
        _last_isrc_registry_sync_summary=None,
        _log_event=mock.Mock(),
        logger=mock.Mock(),
    )

    paths = registry_controller._profile_paths_for_isrc_registry(app)
    assert paths == [
        Path(str(profile_one.expanduser().resolve(strict=False))),
        Path(str(profile_two.expanduser().resolve(strict=False))),
    ]

    registry_controller._sync_application_isrc_registry(app)

    registry.sync_profiles.assert_called_once_with(paths)
    assert app._last_isrc_registry_sync_summary is summary
    app._log_event.assert_called_once()

    app.application_isrc_registry = SimpleNamespace(
        sync_profiles=mock.Mock(side_effect=RuntimeError("sync failed"))
    )
    registry_controller._sync_application_isrc_registry(app)
    app.logger.warning.assert_called()


def test_root_attr_prefix_paths_and_sync_noop_fallbacks(monkeypatch, tmp_path):
    override = object()
    monkeypatch.setitem(
        registry_controller.sys.modules,
        "isrc_manager.main_window",
        SimpleNamespace(QMessageBox=override),
    )
    assert registry_controller._root_attr("QMessageBox", None) is override

    assert registry_controller.load_isrc_prefix(SimpleNamespace(settings_reads=None)) == ""

    current_path = tmp_path / "current.sqlite"
    app = SimpleNamespace(
        profile_store=SimpleNamespace(list_profiles=mock.Mock(side_effect=RuntimeError("boom"))),
        current_db_path=str(current_path),
    )
    assert registry_controller._profile_paths_for_isrc_registry(app) == [
        Path(str(current_path.expanduser().resolve(strict=False)))
    ]

    registry_controller._sync_application_isrc_registry(
        SimpleNamespace(application_isrc_registry=None)
    )


def test_conflict_format_lookup_reserve_activate_and_release(monkeypatch):
    messages = []

    class FakeMessageBox:
        @classmethod
        def warning(cls, *args):
            messages.append(args)

    monkeypatch.setattr(
        registry_controller,
        "_root_attr",
        lambda name, fallback: FakeMessageBox if name == "QMessageBox" else fallback,
    )
    conflict = _conflict()
    registry = SimpleNamespace(
        find_conflict=mock.Mock(return_value=conflict),
        reserve_isrc=mock.Mock(return_value=conflict),
        activate_isrc=mock.Mock(return_value=conflict),
        release_reserved_isrc=mock.Mock(),
    )
    app = SimpleNamespace(
        application_isrc_registry=registry,
        current_db_path="/profiles/current.sqlite",
        _current_profile_name=mock.Mock(return_value="Current"),
        _format_isrc_registry_conflict=lambda item: registry_controller._format_isrc_registry_conflict(
            item
        ),
        _log_event=mock.Mock(),
        logger=mock.Mock(),
    )

    assert (
        registry_controller._format_isrc_registry_conflict(conflict)
        == "NL-ABC-26-01001 is already claimed by track #12 'Claimed Song' in Demo."
    )
    assert registry_controller._isrc_registry_conflict(app, "NL-ABC-26-01001") is conflict
    assert (
        registry_controller._reserve_isrc_claim_for_profile(
            app,
            "NL-ABC-26-01001",
            track_title="New Song",
        )
        is False
    )
    assert messages

    registry_controller._activate_isrc_claim_for_track(
        app,
        "NL-ABC-26-01001",
        track_id=77,
        track_title="New Song",
    )
    app._log_event.assert_called_once()

    registry_controller._release_reserved_isrc_claim(app, "NL-ABC-26-01001")
    registry.release_reserved_isrc.assert_called_once_with(
        "NL-ABC-26-01001",
        profile_path="/profiles/current.sqlite",
    )

    registry.find_conflict.side_effect = RuntimeError("lookup failed")
    assert registry_controller._isrc_registry_conflict(app, "NL-ABC-26-01002") is None
    app.logger.warning.assert_called()


def test_registry_claim_guardrails_and_exception_fallbacks(monkeypatch):
    messages = []

    class FakeMessageBox:
        @classmethod
        def warning(cls, *args):
            messages.append(args)

    monkeypatch.setattr(
        registry_controller,
        "_root_attr",
        lambda name, fallback: FakeMessageBox if name == "QMessageBox" else fallback,
    )

    bare_app = SimpleNamespace(
        application_isrc_registry=None,
        current_db_path="/profiles/current.sqlite",
        logger=mock.Mock(),
    )
    assert registry_controller._isrc_registry_conflict(bare_app, "NL-ABC-26-01001") is None
    assert registry_controller._reserve_isrc_claim_for_profile(bare_app, "not-an-isrc") is True
    registry_controller._activate_isrc_claim_for_track(
        bare_app,
        "NL-ABC-26-01001",
        track_id=1,
        track_title="No Registry",
    )
    registry_controller._release_reserved_isrc_claim(bare_app, "NL-ABC-26-01001")

    registry = SimpleNamespace(
        reserve_isrc=mock.Mock(side_effect=RuntimeError("reserve failed")),
        activate_isrc=mock.Mock(side_effect=RuntimeError("activate failed")),
        release_reserved_isrc=mock.Mock(side_effect=RuntimeError("release failed")),
    )
    app = SimpleNamespace(
        application_isrc_registry=registry,
        current_db_path="/profiles/current.sqlite",
        _current_profile_name=mock.Mock(return_value="Current"),
        logger=mock.Mock(),
        _log_event=mock.Mock(),
        _format_isrc_registry_conflict=lambda item: registry_controller._format_isrc_registry_conflict(
            item
        ),
    )

    assert registry_controller._reserve_isrc_claim_for_profile(app, "NL-ABC-26-01001") is True
    registry_controller._activate_isrc_claim_for_track(
        app,
        "NL-ABC-26-01001",
        track_id=7,
        track_title="Activation Failure",
    )
    registry_controller._release_reserved_isrc_claim(app, "NL-ABC-26-01001")
    assert app.logger.warning.call_count == 3

    registry.reserve_isrc = mock.Mock(return_value=None)
    assert registry_controller._reserve_isrc_claim_for_profile(app, "NL-ABC-26-01002") is True
    registry.activate_isrc = mock.Mock(return_value=None)
    registry_controller._activate_isrc_claim_for_track(
        app,
        "NL-ABC-26-01002",
        track_id=8,
        track_title="No Conflict",
    )
    app._log_event.assert_not_called()
    assert not messages


def test_claim_next_generated_isrc_skips_reserved_conflict_then_returns_success():
    generated = iter(["NL-ABC-26-01001", "NL-ABC-26-01002"])
    reserve_results = [False, True]
    app = SimpleNamespace(
        _next_generated_isrc=mock.Mock(side_effect=lambda **kwargs: next(generated)),
        _reserve_isrc_claim_for_profile=mock.Mock(
            side_effect=lambda *args, **kwargs: reserve_results.pop(0)
        ),
    )

    assert (
        registry_controller._claim_next_generated_isrc(
            app,
            release_date=QDate(2026, 5, 25),
            use_release_year=True,
            reserved_compacts={"NLABC2601999"},
            track_title="Song",
        )
        == "NL-ABC-26-01002"
    )
    assert app._next_generated_isrc.call_count == 2
    blocked = app._next_generated_isrc.call_args_list[1].kwargs["reserved_compacts"]
    assert "NLABC2601001" in blocked


def test_claim_next_generated_isrc_stops_when_generator_exhausts():
    app = SimpleNamespace(
        _next_generated_isrc=mock.Mock(return_value=""),
        _reserve_isrc_claim_for_profile=mock.Mock(),
    )

    assert registry_controller._claim_next_generated_isrc(app) == ""
    app._reserve_isrc_claim_for_profile.assert_not_called()


def test_isrc_generation_state_and_next_generated_isrc_cover_invalid_and_ready_paths():
    app = SimpleNamespace(
        conn=object(),
        cursor=object(),
        load_isrc_prefix=mock.Mock(return_value=""),
        load_artist_code=mock.Mock(return_value="01"),
        _isrc_generation_state=lambda: registry_controller._isrc_generation_state(app),
        is_isrc_taken_normalized=mock.Mock(side_effect=lambda value: value.endswith("01001")),
    )

    assert registry_controller._isrc_generation_state(app)[0] == "disabled"
    app.load_isrc_prefix.return_value = "bad"
    assert registry_controller._isrc_generation_state(app)[0] == "error"
    app.load_isrc_prefix.return_value = "NLABC"
    app.load_artist_code.return_value = "x"
    assert registry_controller._isrc_generation_state(app)[0] == "error"
    app.load_artist_code.return_value = "01"
    assert registry_controller._isrc_generation_state(app) == ("ready", "")

    assert (
        registry_controller._next_generated_isrc(
            app,
            release_date=QDate(2027, 1, 2),
            use_release_year=True,
            reserved_compacts={"NLABC2701002"},
        )
        == "NL-ABC-27-01003"
    )

    app.conn = None
    assert registry_controller._next_generated_isrc(app) == ""


def test_next_generated_isrc_handles_not_ready_exceptions_and_exhaustion():
    app = SimpleNamespace(
        conn=object(),
        cursor=object(),
        load_isrc_prefix=mock.Mock(return_value="NLABC"),
        load_artist_code=mock.Mock(return_value="01"),
        _isrc_generation_state=mock.Mock(return_value=("disabled", "not ready")),
        is_isrc_taken_normalized=mock.Mock(),
    )

    assert registry_controller._next_generated_isrc(app) == ""

    app._isrc_generation_state.return_value = ("ready", "")
    app.is_isrc_taken_normalized.side_effect = RuntimeError("lookup offline")
    assert registry_controller._next_generated_isrc(app, release_date=object()) == (
        f"NL-ABC-{registry_controller.datetime.now().year % 100:02d}-01001"
    )

    app.is_isrc_taken_normalized.side_effect = None
    app.is_isrc_taken_normalized.return_value = True
    assert registry_controller._next_generated_isrc(app) == ""


def test_load_isrc_prefix_failure_logs_and_disables_generation():
    app = SimpleNamespace(
        settings_reads=SimpleNamespace(load_isrc_prefix=mock.Mock(side_effect=MemoryError())),
        logger=mock.Mock(),
    )

    assert registry_controller.load_isrc_prefix(app) == ""
    app.logger.warning.assert_called_once()


def test_preview_and_update_generated_fields_set_placeholders_and_toggle_state():
    generated = _Field()
    app = SimpleNamespace(
        record_id_field=_Field(),
        entry_date_preview_field=_Field(),
        generated_isrc_field=generated,
        prev_release_toggle=_Toggle(True),
        _isrc_generation_state=mock.Mock(return_value=("ready", "")),
        _preview_generated_isrc=mock.Mock(return_value="NL-ABC-26-01001"),
    )

    registry_controller._update_add_data_generated_fields(app)

    assert app.record_id_field.cleared == 1
    assert app.entry_date_preview_field.cleared == 1
    assert generated.text == "NL-ABC-26-01001"
    assert "Generated automatically" in generated.placeholder
    assert app.prev_release_toggle.enabled is True

    app._preview_generated_isrc.return_value = ""
    app._isrc_generation_state.return_value = ("disabled", "disabled message")
    registry_controller._update_add_data_generated_fields(app)
    assert "disabled" in generated.placeholder
    assert generated.tooltip == "disabled message"
    assert app.prev_release_toggle.enabled is False

    app._isrc_generation_state.return_value = ("error", "error message")
    registry_controller._update_add_data_generated_fields(app)
    assert "Fix ISRC settings" in generated.placeholder
    assert generated.tooltip == "error message"


def test_preview_and_update_generated_fields_cover_missing_and_empty_ready_states():
    generated = _Field()
    release_date_field = SimpleNamespace(selectedDate=mock.Mock(side_effect=RuntimeError("closed")))
    app = SimpleNamespace(
        release_date_field=release_date_field,
        prev_release_toggle=_Toggle(False),
        _next_generated_isrc=mock.Mock(return_value="NL-ABC-26-01001"),
    )

    assert registry_controller._preview_generated_isrc(app) == "NL-ABC-26-01001"
    app._next_generated_isrc.assert_called_once_with(release_date=None, use_release_year=False)

    no_generated_field_app = SimpleNamespace(
        record_id_field=_Field(),
        entry_date_preview_field=_Field(),
    )
    registry_controller._update_add_data_generated_fields(no_generated_field_app)
    assert no_generated_field_app.record_id_field.cleared == 1
    assert no_generated_field_app.entry_date_preview_field.cleared == 1

    ready_empty_app = SimpleNamespace(
        generated_isrc_field=generated,
        _isrc_generation_state=mock.Mock(return_value=("ready", "")),
        _preview_generated_isrc=mock.Mock(return_value=""),
    )
    registry_controller._update_add_data_generated_fields(ready_empty_app)
    assert "No free ISRC sequence" in generated.placeholder
    assert "no free sequence" in generated.tooltip


def test_update_generated_fields_skips_preview_when_generation_is_not_ready():
    generated = _Field()
    app = SimpleNamespace(
        generated_isrc_field=generated,
        prev_release_toggle=_Toggle(True),
        _isrc_generation_state=mock.Mock(return_value=("disabled", "settings unavailable")),
        _preview_generated_isrc=mock.Mock(side_effect=AssertionError("preview should be skipped")),
    )

    registry_controller._update_add_data_generated_fields(app)

    assert generated.text == ""
    assert "disabled" in generated.placeholder
    assert generated.tooltip == "settings unavailable"
    assert app.prev_release_toggle.enabled is False
    app._preview_generated_isrc.assert_not_called()


def test_generate_set_prefix_and_taken_checks(monkeypatch):
    messages = []

    class FakeMessageBox:
        @classmethod
        def warning(cls, *args):
            messages.append(("warning", args))

        @classmethod
        def critical(cls, *args):
            messages.append(("critical", args))

    monkeypatch.setattr(
        registry_controller,
        "_root_attr",
        lambda name, fallback: FakeMessageBox if name == "QMessageBox" else fallback,
    )
    release_date_field = SimpleNamespace(selectedDate=mock.Mock(return_value=QDate(2026, 5, 25)))
    prev_release_toggle = SimpleNamespace(isChecked=mock.Mock(return_value=True))
    app = SimpleNamespace(
        release_date_field=release_date_field,
        prev_release_toggle=prev_release_toggle,
        _next_generated_isrc=mock.Mock(return_value="NL-ABC-26-01001"),
        open_settings_dialog=mock.Mock(),
        _apply_single_setting_value=mock.Mock(),
        logger=mock.Mock(),
    )

    assert registry_controller.generate_isrc(app) == "NL-ABC-26-01001"
    app._next_generated_isrc.assert_called_once_with(
        release_date=QDate(2026, 5, 25),
        use_release_year=True,
    )

    registry_controller.set_isrc_prefix(app)
    app.open_settings_dialog.assert_called_once_with(initial_focus="isrc_prefix")
    registry_controller.set_isrc_prefix(app, "bad")
    assert messages[-1][0] == "warning"
    registry_controller.set_isrc_prefix(app, " nlabc ")
    app._apply_single_setting_value.assert_called_once_with("isrc_prefix", "NLABC")

    app._apply_single_setting_value.side_effect = RuntimeError("write failed")
    registry_controller.set_isrc_prefix(app, "NLXYZ")
    assert messages[-1][0] == "critical"

    track_service = SimpleNamespace(is_isrc_taken_normalized=mock.Mock(return_value=True))
    app = SimpleNamespace(
        track_service=track_service,
        cursor=object(),
        _isrc_registry_conflict=mock.Mock(return_value=None),
    )
    assert registry_controller.is_isrc_taken_normalized(app, "NL-ABC-26-01001") is True
    track_service.is_isrc_taken_normalized.return_value = False
    app._isrc_registry_conflict.return_value = _conflict()
    assert registry_controller.is_isrc_taken_normalized(app, "NL-ABC-26-01001") is True
    app._isrc_registry_conflict.return_value = None
    assert registry_controller.is_isrc_taken_normalized(app, "NL-ABC-26-01001") is False

    no_track_service_app = SimpleNamespace(
        track_service=None,
        cursor=object(),
        _isrc_registry_conflict=mock.Mock(return_value=_conflict(track_id=None, track_title="")),
    )
    assert registry_controller.is_isrc_taken_normalized(no_track_service_app, "NLABC2601001")
