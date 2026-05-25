from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from isrc_manager import profile_session


class _Combo:
    def __init__(self):
        self.items: list[tuple[str, str]] = []
        self.index = -1
        self.blocked: list[bool] = []

    def blockSignals(self, blocked: bool) -> None:
        self.blocked.append(bool(blocked))

    def clear(self) -> None:
        self.items.clear()

    def addItem(self, label: str, path: str) -> None:
        self.items.append((label, path))

    def findData(self, path: str) -> int:
        for index, (_label, item_path) in enumerate(self.items):
            if item_path == path:
                return index
        return -1

    def setCurrentIndex(self, index: int) -> None:
        self.index = index

    def currentIndex(self) -> int:
        return self.index

    def itemData(self, index: int):
        return self.items[index][1] if 0 <= index < len(self.items) else None


class _MessageBox:
    Yes = 1
    No = 2
    Warning = 3
    Information = 4
    Critical = 5

    messages: list[tuple[str, tuple]] = []

    @classmethod
    def question(cls, *args):
        cls.messages.append(("question", args))
        return cls.Yes

    @classmethod
    def warning(cls, *args):
        cls.messages.append(("warning", args))

    @classmethod
    def information(cls, *args):
        cls.messages.append(("information", args))

    @classmethod
    def critical(cls, *args):
        cls.messages.append(("critical", args))


def test_reload_profiles_list_blocks_signals_and_selects_requested_path():
    combo = _Combo()
    app = SimpleNamespace(
        profile_combo=combo,
        current_db_path="/profiles/current.db",
        profile_workflows=SimpleNamespace(
            list_profile_choices=mock.Mock(
                return_value=[
                    SimpleNamespace(label="Current", path="/profiles/current.db"),
                    SimpleNamespace(label="Other", path="/profiles/other.db"),
                ]
            )
        ),
    )

    profile_session._reload_profiles_list(app, select_path="/profiles/other.db")

    assert combo.items == [
        ("Current", "/profiles/current.db"),
        ("Other", "/profiles/other.db"),
    ]
    assert combo.index == 1
    assert combo.blocked == [True, False]
    app.profile_workflows.list_profile_choices.assert_called_once_with(
        current_db_path="/profiles/current.db"
    )


def test_on_profile_changed_confirms_and_runs_activation_callback(monkeypatch):
    _MessageBox.messages = []
    monkeypatch.setattr(profile_session, "QMessageBox", _MessageBox)
    combo = _Combo()
    combo.addItem("Other", "/profiles/other.db")
    combo.setCurrentIndex(0)
    activated = []
    app = SimpleNamespace(
        profile_combo=combo,
        current_db_path="/profiles/current.db",
        _activate_profile_in_background=lambda path, **kwargs: activated.append((path, kwargs)),
        _log_event=mock.Mock(),
        _audit=mock.Mock(),
        _audit_commit=mock.Mock(),
        session_history_manager=SimpleNamespace(record_profile_switch=mock.Mock()),
        _refresh_history_actions=mock.Mock(),
    )

    profile_session._on_profile_changed(app, 0)

    assert activated[0][0] == "/profiles/other.db"
    callback = activated[0][1]["on_activated"]
    callback("/profiles/other.db")
    app._log_event.assert_called_once()
    app._audit.assert_called_once()
    app.session_history_manager.record_profile_switch.assert_called_once()

    profile_session._on_profile_changed(app, -1)
    combo.items[0] = ("Current", "/profiles/current.db")
    profile_session._on_profile_changed(app, 0)
    assert len(activated) == 1


def test_create_new_profile_handles_cancel_exists_and_success(monkeypatch):
    _MessageBox.messages = []
    monkeypatch.setattr(profile_session, "QMessageBox", _MessageBox)

    class FakeInputDialog:
        result = ("", False)

        @classmethod
        def getText(cls, *args):
            return cls.result

    monkeypatch.setattr(profile_session, "QInputDialog", FakeInputDialog)
    activated = []
    app = SimpleNamespace(
        current_db_path="/profiles/current.db",
        profile_workflows=SimpleNamespace(build_new_profile_path=mock.Mock()),
        _clear_table_settings_for_path=mock.Mock(),
        _activate_profile_in_background=lambda path, **kwargs: activated.append((path, kwargs)),
        _log_event=mock.Mock(),
        _audit=mock.Mock(),
        _audit_commit=mock.Mock(),
        session_history_manager=SimpleNamespace(record_profile_create=mock.Mock()),
        _refresh_history_actions=mock.Mock(),
    )

    profile_session.create_new_profile(app)
    assert activated == []

    FakeInputDialog.result = ("Existing.db", True)
    app.profile_workflows.build_new_profile_path.side_effect = FileExistsError
    profile_session.create_new_profile(app)
    assert _MessageBox.messages[-1][0] == "warning"

    app.profile_workflows.build_new_profile_path.side_effect = None
    app.profile_workflows.build_new_profile_path.return_value = Path("/profiles/new.db")
    FakeInputDialog.result = ("New.db", True)
    profile_session.create_new_profile(app)

    assert activated[0][0] == "/profiles/new.db"
    app._clear_table_settings_for_path.assert_called_once_with("/profiles/new.db")
    activated[0][1]["on_activated"]("/profiles/new.db")
    app.session_history_manager.record_profile_create.assert_called_once()
    assert _MessageBox.messages[-1][0] == "information"


def test_browse_profile_activates_selected_database_and_records_switch(monkeypatch):
    _MessageBox.messages = []

    class FakeFileDialog:
        result = ("", "")

        @classmethod
        def getOpenFileName(cls, *args):
            return cls.result

    monkeypatch.setattr(profile_session, "QFileDialog", FakeFileDialog)
    activated = []
    app = SimpleNamespace(
        current_db_path="/profiles/current.db",
        database_dir=Path("/profiles"),
        _activate_profile_in_background=lambda path, **kwargs: activated.append((path, kwargs)),
        _log_event=mock.Mock(),
        _audit=mock.Mock(),
        _audit_commit=mock.Mock(),
        session_history_manager=SimpleNamespace(record_profile_switch=mock.Mock()),
        _refresh_history_actions=mock.Mock(),
    )

    profile_session.browse_profile(app)
    assert activated == []

    FakeFileDialog.result = ("/profiles/external.db", "")
    profile_session.browse_profile(app)
    assert activated[0][0] == "/profiles/external.db"
    activated[0][1]["on_activated"]("/profiles/external.db")
    app._log_event.assert_called_once()
    app.session_history_manager.record_profile_switch.assert_called_once()


def test_remove_selected_profile_deletes_current_profile_and_opens_fallback(monkeypatch):
    _MessageBox.messages = []
    monkeypatch.setattr(profile_session, "QMessageBox", _MessageBox)
    combo = _Combo()
    combo.addItem("Current", "/profiles/current.db")
    combo.setCurrentIndex(0)
    app = SimpleNamespace(
        profile_combo=combo,
        current_db_path="/profiles/current.db",
        session_history_manager=SimpleNamespace(
            capture_profile_snapshot=mock.Mock(return_value="/snap/current.zip"),
            record_profile_remove=mock.Mock(),
        ),
        _close_database_connection=mock.Mock(),
        profile_workflows=SimpleNamespace(
            delete_profile=mock.Mock(
                return_value=SimpleNamespace(
                    deleting_current=True,
                    fallback_path="/profiles/fallback.db",
                )
            )
        ),
        _sync_application_isrc_registry=mock.Mock(),
        _reload_profiles_list=mock.Mock(),
        open_database=mock.Mock(),
        _schedule_owner_party_bootstrap=mock.Mock(),
        refresh_table_preserve_view=mock.Mock(),
        populate_all_comboboxes=mock.Mock(),
        _log_event=mock.Mock(),
        _audit=mock.Mock(),
        _audit_commit=mock.Mock(),
        _refresh_history_actions=mock.Mock(),
        conn=SimpleNamespace(rollback=mock.Mock()),
        logger=mock.Mock(),
    )

    profile_session.remove_selected_profile(app)

    app._close_database_connection.assert_called_once()
    app.profile_workflows.delete_profile.assert_called_once_with(
        "/profiles/current.db",
        "/profiles/current.db",
    )
    app.open_database.assert_called_once_with("/profiles/fallback.db")
    app.session_history_manager.record_profile_remove.assert_called_once()
    assert _MessageBox.messages[-1][0] == "information"


def test_close_database_connection_stops_services_and_resets_profile_state():
    app = SimpleNamespace(
        _stop_audio_waveform_cache_worker=mock.Mock(),
        auto_snapshot_timer=SimpleNamespace(stop=mock.Mock()),
        quality_dashboard_dialog=SimpleNamespace(close=mock.Mock()),
        _last_auto_snapshot_marker=22,
        database_session=SimpleNamespace(close=mock.Mock()),
        conn=object(),
        cursor=object(),
        track_service=object(),
        background_service_factory=SimpleNamespace(db_path="/profiles/current.db"),
        _refresh_catalog_workspace_docks=mock.Mock(),
    )

    profile_session._close_database_connection(app)

    app._stop_audio_waveform_cache_worker.assert_called_once_with(wait=False)
    app.auto_snapshot_timer.stop.assert_called_once()
    assert app.quality_dashboard_dialog is None
    app.database_session.close.assert_called_once()
    assert app.conn is None
    assert app.cursor is None
    assert app.track_service is None
    assert app.conversion_service is not None
    assert app.background_service_factory.db_path is None
    assert app._background_write_lock is None
    app._refresh_catalog_workspace_docks.assert_called_once()


def test_prepare_database_for_open_blocking_reports_phase_and_handles_failure():
    progress = []
    app = SimpleNamespace(
        _report_startup_phase=mock.Mock(),
        _startup_progress_callback=mock.Mock(return_value=lambda *args: progress.append(args)),
        _prepare_database_session=mock.Mock(return_value="/profiles/demo.db"),
        logger=mock.Mock(),
    )

    assert (
        profile_session._prepare_database_for_open_blocking(
            app,
            "/profiles/demo.db",
            title="Open",
            description="Prepare",
        )
        is True
    )
    app._prepare_database_session.assert_called_once()

    app._prepare_database_session.side_effect = RuntimeError("prepare failed")
    assert (
        profile_session._prepare_database_for_open_blocking(
            app,
            "/profiles/demo.db",
            title="Open",
            description="Prepare",
        )
        is False
    )
    app.logger.warning.assert_called()
    app.logger.debug.assert_called()


def test_prepare_profile_database_background_wires_worker_progress_and_error_handler():
    submitted = {}
    progress_updates = []
    failure = object()
    app = SimpleNamespace(
        _prepare_database_session=mock.Mock(return_value="/profiles/prepared.db"),
        _submit_background_task=lambda **kwargs: submitted.update(kwargs) or "task-1",
        _show_background_task_error=mock.Mock(),
    )

    task_id = profile_session._prepare_profile_database_background(
        app,
        "/profiles/demo.db",
        title="Prepare",
        description="Preparing database",
        show_dialog=False,
        on_success=mock.Mock(),
        progress_callback=lambda *args: progress_updates.append(args),
    )

    assert task_id == "task-1"
    ctx = SimpleNamespace(
        set_status=mock.Mock(),
        report_progress=mock.Mock(),
    )
    assert submitted["task_fn"](ctx) == "/profiles/prepared.db"
    ctx.set_status.assert_called_once_with("Preparing database")
    app._prepare_database_session.assert_called_once()

    update = SimpleNamespace(value=1, maximum=4, message="step")
    submitted["on_progress"](update)
    assert progress_updates == [(1, 4, "step")]

    submitted["on_error"](failure)
    app._show_background_task_error.assert_called_once_with(
        "Prepare",
        failure,
        user_message="Could not prepare the selected profile:",
    )
