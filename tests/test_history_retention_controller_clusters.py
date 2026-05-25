from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest

from isrc_manager import history_retention_controller as retention
from isrc_manager.constants import (
    DEFAULT_AUTO_SNAPSHOT_ENABLED,
    DEFAULT_AUTO_SNAPSHOT_INTERVAL_MINUTES,
    MAX_AUTO_SNAPSHOT_INTERVAL_MINUTES,
)
from isrc_manager.history import HistoryCleanupBlockedError
from isrc_manager.services import HistoryRetentionSettings


class _StatusBar:
    def __init__(self):
        self.messages: list[tuple[str, int]] = []

    def showMessage(self, text: str, timeout: int) -> None:
        self.messages.append((text, timeout))


def test_current_settings_and_application_budget_helpers_use_defaults_and_registry_fallbacks():
    app = SimpleNamespace(
        settings_reads=None,
        _application_history_storage_budget_mb=lambda *, default: int(default) + 5,
    )

    assert retention._current_auto_snapshot_settings(app) == (
        DEFAULT_AUTO_SNAPSHOT_ENABLED,
        DEFAULT_AUTO_SNAPSHOT_INTERVAL_MINUTES,
    )
    settings = retention._current_history_retention_settings(app)
    assert settings.storage_budget_mb == HistoryRetentionSettings().storage_budget_mb + 5

    app.settings_reads = SimpleNamespace(
        load_auto_snapshot_settings=mock.Mock(
            return_value=SimpleNamespace(enabled=False, interval_minutes=17)
        ),
        load_history_retention_settings=mock.Mock(
            return_value=HistoryRetentionSettings(storage_budget_mb=300)
        ),
    )
    assert retention._current_auto_snapshot_settings(app) == (False, 17)
    assert retention._current_history_retention_settings(app).storage_budget_mb == 305

    assert (
        retention._application_history_storage_budget_mb(
            SimpleNamespace(application_isrc_registry=None), default=44
        )
        == 44
    )
    assert (
        retention._application_history_storage_budget_mb(
            SimpleNamespace(
                application_isrc_registry=SimpleNamespace(
                    read_history_storage_budget_mb=mock.Mock(side_effect=RuntimeError("boom"))
                )
            ),
            default=45,
        )
        == 45
    )
    registry = SimpleNamespace(write_history_storage_budget_mb=mock.Mock(return_value=512))
    assert (
        retention._set_application_history_storage_budget_mb(
            SimpleNamespace(application_isrc_registry=registry), 256
        )
        == 512
    )
    registry.write_history_storage_budget_mb.assert_called_once_with(256)


def test_path_size_recursive_counts_files_and_directories_and_tolerates_bad_paths(tmp_path):
    file_path = tmp_path / "history.db"
    file_path.write_bytes(b"abc")
    nested = tmp_path / "managed"
    nested.mkdir()
    (nested / "blob.bin").write_bytes(b"abcdef")

    assert retention._path_size_recursive(None) == 0
    assert retention._path_size_recursive(object()) == 0
    assert retention._path_size_recursive(file_path) >= 3
    assert retention._path_size_recursive(tmp_path) >= 9


def test_prepare_history_storage_runs_noninteractive_cleanup_when_it_can_make_room(monkeypatch):
    status = _StatusBar()
    refresh_actions = mock.Mock()
    dialog = SimpleNamespace(isVisible=mock.Mock(return_value=True), refresh_data=mock.Mock())
    projection = SimpleNamespace(
        budget_bytes=100,
        projected_over_budget_bytes=25,
        candidate_items=[SimpleNamespace(item_key="old-snapshot")],
        projected_over_budget_after_cleanup_bytes=0,
        blocked_by_protected_items=False,
    )

    class FakeCleanupService:
        def __init__(self, manager):
            self.manager = manager

        def preview_storage_projection(self, settings, *, additional_bytes):
            assert additional_bytes == 40
            return projection

        def cleanup_selected(self, item_keys):
            assert item_keys == ["old-snapshot"]
            return SimpleNamespace(removed_item_keys=["old-snapshot"])

    app = SimpleNamespace(
        history_manager=object(),
        settings_reads=object(),
        history_dialog=dialog,
        logger=mock.Mock(),
        _refresh_history_actions=refresh_actions,
        _current_history_retention_settings=lambda: HistoryRetentionSettings(
            auto_cleanup_enabled=True
        ),
        _apply_history_snapshot_retention_policy=mock.Mock(return_value=None),
        statusBar=lambda: status,
    )
    monkeypatch.setattr(retention, "HistoryStorageCleanupService", FakeCleanupService)

    assert (
        retention._prepare_history_storage_for_projected_growth(
            app,
            trigger_label="automatic snapshot",
            additional_bytes=40,
            interactive=False,
        )
        is True
    )
    refresh_actions.assert_called_once()
    dialog.refresh_data.assert_called_once()


def test_prepare_history_storage_reports_noninteractive_blocked_projection(monkeypatch):
    status = _StatusBar()
    projection = SimpleNamespace(
        budget_bytes=100,
        projected_over_budget_bytes=25,
        projected_total_bytes=125,
        candidate_items=[],
        projected_over_budget_after_cleanup_bytes=25,
        blocked_by_protected_items=True,
        auto_cleanup_enabled=False,
        reclaimable_bytes=0,
        current_total_bytes=95,
        additional_bytes=30,
    )

    class FakeCleanupService:
        def __init__(self, manager):
            self.manager = manager

        def preview_storage_projection(self, settings, *, additional_bytes):
            return projection

    app = SimpleNamespace(
        history_manager=object(),
        settings_reads=object(),
        logger=mock.Mock(),
        _human_size=lambda value: f"{value} B",
        _current_history_retention_settings=lambda: HistoryRetentionSettings(
            auto_cleanup_enabled=False
        ),
        _apply_history_snapshot_retention_policy=mock.Mock(return_value=None),
        statusBar=lambda: status,
    )
    monkeypatch.setattr(retention, "HistoryStorageCleanupService", FakeCleanupService)

    assert (
        retention._prepare_history_storage_for_projected_growth(
            app,
            trigger_label="manual snapshot",
            additional_bytes=30,
            interactive=False,
        )
        is False
    )
    assert "manual snapshot" in status.messages[-1][0]
    assert "125 B" in status.messages[-1][0]
    app.logger.info.assert_called_once()


@pytest.mark.parametrize(
    ("clicked_name", "expected_result", "opens_admin"),
    [
        ("continue", True, False),
        ("cleanup", False, True),
        ("cancel", False, False),
    ],
)
def test_prepare_history_storage_interactive_buttons(
    monkeypatch, clicked_name, expected_result, opens_admin
):
    buttons = {}

    class FakeMessageBox:
        Warning = 1
        AcceptRole = 2
        ActionRole = 3
        Cancel = 4

        def __init__(self, parent):
            self.parent = parent

        def setIcon(self, icon):
            self.icon = icon

        def setWindowTitle(self, title):
            self.title = title

        def setText(self, text):
            self.text = text

        def addButton(self, label, role=None):
            button = object()
            if label == "Continue":
                buttons["continue"] = button
            elif label == "Open Application Storage Admin":
                buttons["cleanup"] = button
            elif label == self.Cancel:
                buttons["cancel"] = button
            return button

        def setDefaultButton(self, button):
            self.default_button = button

        def exec(self):
            return None

        def clickedButton(self):
            return buttons[clicked_name]

    projection = SimpleNamespace(
        budget_bytes=100,
        projected_over_budget_bytes=10,
        projected_total_bytes=110,
        current_total_bytes=80,
        additional_bytes=30,
        auto_cleanup_enabled=True,
        reclaimable_bytes=5,
        blocked_by_protected_items=False,
        candidate_items=[],
        projected_over_budget_after_cleanup_bytes=10,
    )

    class FakeCleanupService:
        def __init__(self, manager):
            self.manager = manager

        def preview_storage_projection(self, settings, *, additional_bytes):
            return projection

    app = SimpleNamespace(
        history_manager=object(),
        settings_reads=object(),
        _human_size=lambda value: f"{value} B",
        _current_history_retention_settings=lambda: HistoryRetentionSettings(),
        _apply_history_snapshot_retention_policy=mock.Mock(return_value=None),
        open_application_storage_admin_dialog=mock.Mock(),
    )
    monkeypatch.setattr(retention, "HistoryStorageCleanupService", FakeCleanupService)
    monkeypatch.setattr(retention, "QMessageBox", FakeMessageBox)

    assert (
        retention._prepare_history_storage_for_projected_growth(
            app,
            trigger_label="bulk import",
            additional_bytes=30,
            interactive=True,
        )
        is expected_result
    )
    assert app.open_application_storage_admin_dialog.called is opens_admin


def test_enforce_history_storage_budget_handles_removed_items_and_open_admin_prompt(monkeypatch):
    status = _StatusBar()
    refresh_actions = mock.Mock()
    dialog = SimpleNamespace(isVisible=mock.Mock(return_value=True), refresh_data=mock.Mock())
    result = SimpleNamespace(
        removed_item_keys=["old"],
        over_budget_bytes=64,
        total_bytes=2048,
        budget_bytes=1024,
        blocked_by_protected_items=False,
    )

    class FakeCleanupService:
        def __init__(self, manager):
            self.manager = manager

        def enforce_storage_budget(self, settings):
            return result

    class FakeMessageBox:
        Yes = 1
        No = 2

        @classmethod
        def question(cls, *args):
            return cls.Yes

    app = SimpleNamespace(
        history_manager=object(),
        settings_reads=object(),
        history_dialog=dialog,
        logger=mock.Mock(),
        _last_history_budget_warning_signature=None,
        _human_size=lambda value: f"{value} B",
        _refresh_history_actions=refresh_actions,
        _current_history_retention_settings=lambda: HistoryRetentionSettings(),
        _apply_history_snapshot_retention_policy=mock.Mock(return_value=None),
        open_application_storage_admin_dialog=mock.Mock(),
        statusBar=lambda: status,
    )
    monkeypatch.setattr(retention, "HistoryStorageCleanupService", FakeCleanupService)
    monkeypatch.setattr(retention, "QMessageBox", FakeMessageBox)

    retention._enforce_history_storage_budget(app, trigger_label="save", interactive=False)

    refresh_actions.assert_called_once()
    dialog.refresh_data.assert_called_once()
    assert "removed 1 item" in status.messages[-1][0]
    app.open_application_storage_admin_dialog.assert_called_once()


def test_enforce_history_storage_budget_reports_blocked_cleanup_when_interactive(monkeypatch):
    warnings = []

    class FakeCleanupService:
        def __init__(self, manager):
            self.manager = manager

        def enforce_storage_budget(self, settings):
            raise HistoryCleanupBlockedError("protected undo boundary")

    class FakeMessageBox:
        @classmethod
        def warning(cls, *args):
            warnings.append(args)

    app = SimpleNamespace(
        history_manager=object(),
        settings_reads=object(),
        logger=mock.Mock(),
        _current_history_retention_settings=lambda: HistoryRetentionSettings(),
        _apply_history_snapshot_retention_policy=mock.Mock(return_value=None),
    )
    monkeypatch.setattr(retention, "HistoryStorageCleanupService", FakeCleanupService)
    monkeypatch.setattr(retention, "QMessageBox", FakeMessageBox)

    retention._enforce_history_storage_budget(app, trigger_label="cleanup", interactive=True)

    app.logger.warning.assert_called_once()
    assert warnings
    assert "protected undo boundary" in str(warnings[0])


def test_auto_snapshot_marker_skips_file_and_snapshot_boundary_actions():
    entries = {
        3: SimpleNamespace(entry_id=3, action_type="file.export_json", parent_id=2),
        2: SimpleNamespace(entry_id=2, action_type="db.verify", parent_id=1),
        1: SimpleNamespace(entry_id=1, action_type="track.update", parent_id=None),
    }
    manager = SimpleNamespace(
        get_current_entry=mock.Mock(return_value=entries[3]),
        fetch_entry=mock.Mock(side_effect=lambda entry_id: entries.get(entry_id)),
    )

    assert retention._current_auto_snapshot_marker(SimpleNamespace(history_manager=manager)) == 1

    manager.get_current_entry.return_value = SimpleNamespace(
        entry_id=4,
        action_type="snapshot.create",
        parent_id=None,
    )
    assert retention._current_auto_snapshot_marker(SimpleNamespace(history_manager=manager)) is None


def test_refresh_auto_snapshot_schedule_stops_or_clamps_timer_interval():
    timer = SimpleNamespace(
        started=[],
        stopped=0,
        _interval=0,
        _active=False,
        interval=lambda: timer._interval,
        isActive=lambda: timer._active,
        start=lambda interval: timer.started.append(interval),
        stop=lambda: setattr(timer, "stopped", timer.stopped + 1),
    )

    app = SimpleNamespace(
        auto_snapshot_timer=timer,
        history_manager=None,
        settings_reads=None,
        _last_auto_snapshot_marker=99,
    )
    retention._refresh_auto_snapshot_schedule(app)
    assert timer.stopped == 1
    assert app._last_auto_snapshot_marker is None

    app.history_manager = object()
    app.settings_reads = object()
    app._current_auto_snapshot_settings = lambda: (True, MAX_AUTO_SNAPSHOT_INTERVAL_MINUTES + 999)
    retention._refresh_auto_snapshot_schedule(app)
    assert timer.started[-1] == MAX_AUTO_SNAPSHOT_INTERVAL_MINUTES * 60 * 1000


def test_on_auto_snapshot_timer_captures_snapshot_and_enforces_budget(monkeypatch):
    status = _StatusBar()
    dialog = SimpleNamespace(isVisible=mock.Mock(return_value=True), refresh_data=mock.Mock())
    snapshot = SimpleNamespace(snapshot_id=5, label="Automatic Snapshot 2026-05-25 10:00")
    history_manager = SimpleNamespace(capture_snapshot=mock.Mock(return_value=snapshot))
    app = SimpleNamespace(
        history_manager=history_manager,
        settings_reads=object(),
        auto_snapshot_timer=SimpleNamespace(stop=mock.Mock()),
        _last_auto_snapshot_marker=None,
        _current_auto_snapshot_settings=lambda: (True, 15),
        _current_auto_snapshot_marker=mock.Mock(return_value=44),
        _estimate_history_snapshot_capture_bytes=mock.Mock(return_value=123),
        _prepare_history_storage_for_projected_growth=mock.Mock(return_value=True),
        _log_event=mock.Mock(),
        _enforce_history_storage_budget=mock.Mock(),
        history_dialog=dialog,
        logger=mock.Mock(),
        statusBar=lambda: status,
    )

    retention._on_auto_snapshot_timer(app)

    history_manager.capture_snapshot.assert_called_once()
    assert app._last_auto_snapshot_marker == 44
    app._log_event.assert_called_once()
    dialog.refresh_data.assert_called_once()
    app._enforce_history_storage_budget.assert_called_once_with(trigger_label="automatic snapshot")
    assert "Automatic snapshot created" in status.messages[-1][0]

    app._current_auto_snapshot_settings = lambda: (False, 15)
    retention._on_auto_snapshot_timer(app)
    app.auto_snapshot_timer.stop.assert_called_once()


def test_estimate_history_snapshot_capture_bytes_includes_managed_directories(
    monkeypatch, tmp_path
):
    db_path = tmp_path / "profile.sqlite"
    managed_root = tmp_path / "managed"
    managed_root.mkdir()
    manager = SimpleNamespace(
        db_path=db_path,
        managed_root=managed_root,
        MANAGED_DIRECTORIES=("assets", "exports"),
    )
    calls = []
    sizes = {
        db_path: 10,
        managed_root / "assets": 20,
        managed_root / "exports": 30,
    }

    app = SimpleNamespace(
        history_manager=manager,
        _path_size_recursive=lambda path: calls.append(Path(path)) or sizes[Path(path)],
    )

    assert retention._estimate_history_snapshot_capture_bytes(app) == 60
    assert calls == [db_path, managed_root / "assets", managed_root / "exports"]
