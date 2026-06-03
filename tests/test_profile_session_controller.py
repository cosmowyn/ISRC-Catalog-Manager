from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest

from isrc_manager import profile_session
from isrc_manager.services.database_security import (
    DatabaseSessionPasswordManager,
    InvalidDatabasePasswordError,
    SQLCipherDatabaseService,
)
from tests.qt_test_helpers import require_qapplication


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


class _Settings:
    def __init__(self):
        self.values: dict[str, object] = {}
        self.synced = False

    def value(self, key: str, default=None):
        return self.values.get(key, default)

    def setValue(self, key: str, value) -> None:
        self.values[key] = value

    def sync(self) -> None:
        self.synced = True


class _ProfileMigrationMessageBox:
    Warning = 3
    AcceptRole = 10
    DestructiveRole = 11
    Cancel = 12
    next_choice = "open"
    instances: list["_ProfileMigrationMessageBox"] = []

    def __init__(self, *args):
        del args
        self.buttons: dict[str, object] = {}
        self.checkbox = None
        self.clicked = None
        self.text = ""
        self.informative_text = ""
        type(self).instances.append(self)

    def setIcon(self, *args):
        del args

    def setWindowTitle(self, *args):
        del args

    def setText(self, text: str) -> None:
        self.text = text

    def setInformativeText(self, text: str) -> None:
        self.informative_text = text

    def addButton(self, *args):
        label = str(args[0])
        if label == "Encrypt Now":
            key = "encrypt"
        elif label == "Open Unencrypted":
            key = "open"
        elif args[0] == self.Cancel:
            key = "cancel"
        else:
            key = label
        button = object()
        self.buttons[key] = button
        return button

    def setCheckBox(self, checkbox) -> None:
        self.checkbox = checkbox

    def setDefaultButton(self, *args):
        del args

    def exec(self) -> None:
        self.clicked = self.buttons[type(self).next_choice]

    def clickedButton(self):
        return self.clicked

    @classmethod
    def warning(cls, *args):
        _MessageBox.warning(*args)

    @classmethod
    def information(cls, *args):
        _MessageBox.information(*args)

    @classmethod
    def critical(cls, *args):
        _MessageBox.critical(*args)


class _CheckBox:
    next_checked = False

    def __init__(self, text: str):
        self.text = text

    def isChecked(self) -> bool:
        return bool(type(self).next_checked)


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


def test_prompt_profile_removal_choice_uses_profile_workflow_choices(monkeypatch):
    captured: dict[str, object] = {}

    class FakeRemovalDialog:
        def __init__(self, parent, choices):
            captured["parent"] = parent
            captured["choices"] = choices

        def exec(self):
            return profile_session.QDialog.Accepted

        def selected_profile_path(self):
            return "/profiles/other.db"

    monkeypatch.setattr(profile_session, "ProfileRemovalDialog", FakeRemovalDialog)
    choices = [
        SimpleNamespace(label="Current", path="/profiles/current.db"),
        SimpleNamespace(label="Other", path="/profiles/other.db"),
    ]
    app = SimpleNamespace(
        current_db_path="/profiles/current.db",
        profile_workflows=SimpleNamespace(list_profile_choices=mock.Mock(return_value=choices)),
    )

    assert profile_session._prompt_profile_removal_choice(app) == "/profiles/other.db"
    assert captured["parent"] is app
    assert captured["choices"] == choices
    app.profile_workflows.list_profile_choices.assert_called_once_with(
        current_db_path="/profiles/current.db"
    )


def test_prompt_profile_removal_choice_reports_empty_profile_list(monkeypatch):
    _MessageBox.messages = []
    monkeypatch.setattr(profile_session, "QMessageBox", _MessageBox)
    app = SimpleNamespace(
        current_db_path="/profiles/current.db",
        profile_workflows=SimpleNamespace(list_profile_choices=mock.Mock(return_value=[])),
    )

    assert profile_session._prompt_profile_removal_choice(app) is None
    assert _MessageBox.messages[-1][0] == "information"


def test_create_new_profile_handles_cancel_exists_and_success(monkeypatch):
    _MessageBox.messages = []
    monkeypatch.setattr(profile_session, "QMessageBox", _MessageBox)

    class FakeInputDialog:
        results = [("", False)]

        @classmethod
        def getText(cls, *args):
            del args
            return cls.results.pop(0)

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

    FakeInputDialog.results = [("Existing.db", True)]
    app.profile_workflows.build_new_profile_path.side_effect = FileExistsError
    profile_session.create_new_profile(app)
    assert _MessageBox.messages[-1][0] == "warning"

    app.profile_workflows.build_new_profile_path.side_effect = None
    app.profile_workflows.build_new_profile_path.return_value = Path("/profiles/new.db")
    FakeInputDialog.results = [
        ("New.db", True),
        ("valid-secret-123", True),
        ("valid-secret-123", True),
    ]
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


def test_change_current_database_password_rekeys_encrypted_profile(monkeypatch, tmp_path):
    _MessageBox.messages = []
    monkeypatch.setattr(profile_session, "QMessageBox", _MessageBox)
    db_path = tmp_path / "catalog.db"
    security_service = SQLCipherDatabaseService()
    conn = security_service.open(db_path, "current-secret-123")
    try:
        conn.execute("CREATE TABLE demo(value TEXT)")
        conn.execute("INSERT INTO demo(value) VALUES ('ready')")
        conn.commit()
    finally:
        conn.close()

    class FakeInputDialog:
        results = [
            ("current-secret-123", True),
            ("changed-secret-123", True),
            ("changed-secret-123", True),
        ]

        @classmethod
        def getText(cls, *args):
            del args
            return cls.results.pop(0)

    monkeypatch.setattr(profile_session, "QInputDialog", FakeInputDialog)
    passwords = DatabaseSessionPasswordManager()
    app = SimpleNamespace(
        current_db_path=str(db_path),
        database_security_service=security_service,
        database_passwords=passwords,
    )

    assert profile_session.change_current_database_password(app) is True
    assert passwords.password_for_database(db_path) == "changed-secret-123"
    with pytest.raises(InvalidDatabasePasswordError):
        security_service.open(db_path, "current-secret-123")
    reopened = security_service.open(db_path, "changed-secret-123")
    try:
        assert reopened.execute("SELECT value FROM demo").fetchone() == ("ready",)
    finally:
        reopened.close()
    assert _MessageBox.messages[-1][0] == "information"


def test_plaintext_profile_warning_can_be_suppressed_when_opened_unencrypted(monkeypatch, tmp_path):
    _MessageBox.messages = []
    _ProfileMigrationMessageBox.instances = []
    _ProfileMigrationMessageBox.next_choice = "open"
    _CheckBox.next_checked = True
    monkeypatch.setattr(profile_session, "QMessageBox", _ProfileMigrationMessageBox)
    monkeypatch.setattr(profile_session, "QCheckBox", _CheckBox)

    db_path = tmp_path / "plain.db"
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE demo(value TEXT)")
    conn.commit()
    conn.close()

    settings = _Settings()
    app = SimpleNamespace(settings=settings)

    assert profile_session._migrate_plaintext_profile_if_requested(app, db_path) is True
    profile_key = (
        f"{profile_session.SUPPRESS_UNENCRYPTED_PROFILE_WARNING_SETTING}/"
        f"{profile_session.database_profile_id(db_path)}"
    )
    assert settings.values[profile_key] is True
    assert profile_session.SUPPRESS_UNENCRYPTED_PROFILE_WARNING_SETTING not in settings.values
    assert settings.synced is True
    assert profile_session.is_plaintext_sqlite_database(db_path) is True
    assert _ProfileMigrationMessageBox.instances[0].checkbox.text.endswith(
        "when I open this profile."
    )

    _ProfileMigrationMessageBox.instances = []
    assert profile_session._migrate_plaintext_profile_if_requested(app, db_path) is True
    assert _ProfileMigrationMessageBox.instances == []

    other_db = tmp_path / "other.db"
    conn = sqlite3.connect(other_db)
    conn.execute("CREATE TABLE demo(value TEXT)")
    conn.commit()
    conn.close()
    assert profile_session._migrate_plaintext_profile_if_requested(app, other_db) is True
    assert len(_ProfileMigrationMessageBox.instances) == 1


def test_plaintext_profile_warning_global_suppression_skips_all_prompts(monkeypatch, tmp_path):
    _ProfileMigrationMessageBox.instances = []
    monkeypatch.setattr(profile_session, "QMessageBox", _ProfileMigrationMessageBox)

    db_path = tmp_path / "plain.db"
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE demo(value TEXT)")
    conn.commit()
    conn.close()
    settings = _Settings()
    settings.values[profile_session.SUPPRESS_UNENCRYPTED_PROFILE_WARNING_SETTING] = True
    app = SimpleNamespace(settings=settings)

    assert profile_session._migrate_plaintext_profile_if_requested(app, db_path) is True
    assert _ProfileMigrationMessageBox.instances == []


def test_plaintext_profile_encryption_writes_backup_to_backup_directory(monkeypatch, tmp_path):
    _MessageBox.messages = []
    _ProfileMigrationMessageBox.instances = []
    _ProfileMigrationMessageBox.next_choice = "encrypt"
    _CheckBox.next_checked = False
    monkeypatch.setattr(profile_session, "QMessageBox", _ProfileMigrationMessageBox)
    monkeypatch.setattr(profile_session, "QCheckBox", _CheckBox)

    db_path = tmp_path / "plain.db"
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE demo(value TEXT)")
    conn.commit()
    conn.close()

    class FakeInputDialog:
        results = [
            ("migration-secret-123", True),
            ("migration-secret-123", True),
        ]

        @classmethod
        def getText(cls, *args):
            del args
            return cls.results.pop(0)

    class FakeSecurityService:
        def __init__(self) -> None:
            self.calls: list[tuple[Path, str, Path]] = []

        def encrypt_plaintext_database(self, path, password, *, backup_path=None):
            backup = Path(backup_path)
            backup.write_bytes(Path(path).read_bytes())
            self.calls.append((Path(path), password, backup))
            return SimpleNamespace(database_path=Path(path), backup_path=backup)

    monkeypatch.setattr(profile_session, "QInputDialog", FakeInputDialog)
    passwords = DatabaseSessionPasswordManager()
    security_service = FakeSecurityService()
    backups_dir = tmp_path / "app-data" / "backups"
    app = SimpleNamespace(
        settings=_Settings(),
        backups_dir=backups_dir,
        database_security_service=security_service,
        database_passwords=passwords,
    )

    assert profile_session._migrate_plaintext_profile_if_requested(app, db_path) is True

    assert len(security_service.calls) == 1
    _source, _password, backup_path = security_service.calls[0]
    assert backup_path.parent == backups_dir
    assert backup_path.suffix == ".db"
    assert backup_path.exists()
    sidecar_path = backup_path.with_suffix(".db.backup.json")
    sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
    assert sidecar["kind"] == "profile_migration_unencrypted"
    assert sidecar["source_db_path"] == str(db_path)
    assert sidecar["metadata"] == {"source": "profile_maintenance"}
    assert passwords.password_for_database(db_path) == "migration-secret-123"
    assert str(backup_path) in _MessageBox.messages[-1][1][2]


def test_plaintext_profile_encryption_tolerates_backup_sidecar_write_failure(monkeypatch, tmp_path):
    _MessageBox.messages = []
    _ProfileMigrationMessageBox.instances = []
    _ProfileMigrationMessageBox.next_choice = "encrypt"
    monkeypatch.setattr(profile_session, "QMessageBox", _ProfileMigrationMessageBox)
    monkeypatch.setattr(profile_session, "QCheckBox", _CheckBox)

    db_path = tmp_path / "plain.db"
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE demo(value TEXT)")
    conn.commit()
    conn.close()

    class FakeInputDialog:
        results = [
            ("migration-secret-123", True),
            ("migration-secret-123", True),
        ]

        @classmethod
        def getText(cls, *args):
            del args
            return cls.results.pop(0)

    class FakeSecurityService:
        def encrypt_plaintext_database(self, path, password, *, backup_path=None):
            del password
            backup = Path(backup_path)
            backup.write_bytes(Path(path).read_bytes())
            return SimpleNamespace(database_path=Path(path), backup_path=backup)

    monkeypatch.setattr(profile_session, "QInputDialog", FakeInputDialog)
    monkeypatch.setattr(
        profile_session,
        "_write_profile_maintenance_backup_sidecar",
        mock.Mock(side_effect=OSError("metadata failed")),
    )
    app = SimpleNamespace(
        settings=_Settings(),
        backups_dir=tmp_path / "backups",
        database_security_service=FakeSecurityService(),
        database_passwords=DatabaseSessionPasswordManager(),
    )

    assert profile_session._migrate_plaintext_profile_if_requested(app, db_path) is True
    assert _MessageBox.messages[-2][0] == "warning"
    assert "metadata could not be written" in _MessageBox.messages[-2][1][2]
    assert _MessageBox.messages[-1][0] == "information"


def test_profile_removal_dialog_requires_explicit_dropdown_choice():
    app = require_qapplication()
    dialog = profile_session.ProfileRemovalDialog(
        None,
        [
            SimpleNamespace(label="Current", path="/profiles/current.db"),
            SimpleNamespace(label="Other", path="/profiles/other.db"),
        ],
    )
    try:
        assert dialog.selected_profile_path() is None
        assert dialog.remove_button is not None
        assert dialog.remove_button.isEnabled() is False

        dialog.profile_combo.setCurrentIndex(2)

        assert dialog.selected_profile_path() == "/profiles/other.db"
        assert dialog.remove_button.isEnabled() is True
    finally:
        dialog.deleteLater()
        app.processEvents()


def test_remove_selected_profile_deletes_current_profile_and_opens_fallback(monkeypatch):
    _MessageBox.messages = []
    monkeypatch.setattr(profile_session, "QMessageBox", _MessageBox)
    monkeypatch.setattr(
        profile_session,
        "_prompt_profile_removal_choice",
        mock.Mock(return_value="/profiles/current.db"),
    )
    app = SimpleNamespace(
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
    assert _MessageBox.messages[0][0] == "question"
    assert "/profiles/current.db" in _MessageBox.messages[0][1][2]
    assert _MessageBox.messages[-1][0] == "information"


def test_remove_selected_profile_uses_dialog_choice_not_toolbar_selection(monkeypatch):
    _MessageBox.messages = []
    monkeypatch.setattr(profile_session, "QMessageBox", _MessageBox)
    prompt = mock.Mock(return_value="/profiles/other.db")
    monkeypatch.setattr(profile_session, "_prompt_profile_removal_choice", prompt)
    combo = _Combo()
    combo.addItem("Current", "/profiles/current.db")
    combo.setCurrentIndex(0)
    app = SimpleNamespace(
        profile_combo=combo,
        current_db_path="/profiles/current.db",
        session_history_manager=SimpleNamespace(
            capture_profile_snapshot=mock.Mock(return_value="/snap/other.zip"),
            record_profile_remove=mock.Mock(),
        ),
        _close_database_connection=mock.Mock(),
        profile_workflows=SimpleNamespace(
            delete_profile=mock.Mock(
                return_value=SimpleNamespace(
                    deleting_current=False,
                    fallback_path=None,
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

    prompt.assert_called_once_with(app)
    app._close_database_connection.assert_not_called()
    app.profile_workflows.delete_profile.assert_called_once_with(
        "/profiles/other.db",
        "/profiles/current.db",
    )
    app.open_database.assert_not_called()
    app.session_history_manager.record_profile_remove.assert_called_once()
    assert _MessageBox.messages[0][0] == "question"
    assert "/profiles/other.db" in _MessageBox.messages[0][1][2]
    assert _MessageBox.messages[-1][0] == "information"


def test_remove_selected_profile_cancel_after_dialog_selection_aborts(monkeypatch):
    _MessageBox.messages = []
    monkeypatch.setattr(profile_session, "QMessageBox", _MessageBox)
    monkeypatch.setattr(
        profile_session,
        "_prompt_profile_removal_choice",
        mock.Mock(return_value="/profiles/other.db"),
    )
    monkeypatch.setattr(_MessageBox, "question", classmethod(lambda cls, *args: cls.No))
    app = SimpleNamespace(
        current_db_path="/profiles/current.db",
        session_history_manager=SimpleNamespace(
            capture_profile_snapshot=mock.Mock(),
            record_profile_remove=mock.Mock(),
        ),
        profile_workflows=SimpleNamespace(delete_profile=mock.Mock()),
    )

    profile_session.remove_selected_profile(app)

    app.session_history_manager.capture_profile_snapshot.assert_not_called()
    app.profile_workflows.delete_profile.assert_not_called()
    app.session_history_manager.record_profile_remove.assert_not_called()


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
    app._refresh_catalog_workspace_docks.assert_not_called()


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
    assert app._last_database_prepare_failure is None

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
    assert profile_session._startup_prepare_failure_matches(app, "/profiles/demo.db") is True
    assert app._last_database_prepare_failure.message == "prepare failed"
    app.logger.warning.assert_called()
    app.logger.debug.assert_called()


def test_startup_recovery_skips_failed_profile_and_remembers_fallback(tmp_path):
    failed_path = tmp_path / "broken.db"
    fallback_path = tmp_path / "healthy.db"
    recovery_path = tmp_path / "startup_recovery.db"
    settings = _Settings()
    passwords = DatabaseSessionPasswordManager()
    passwords.set_password(failed_path, "broken-secret-123")
    app = SimpleNamespace(
        database_dir=tmp_path,
        profile_store=SimpleNamespace(list_profiles=lambda: [str(failed_path), str(fallback_path)]),
        settings=settings,
        database_passwords=passwords,
        _last_database_prepare_failure=SimpleNamespace(
            path=str(failed_path),
            error_type="DatabaseError",
            message="database disk image is malformed",
        ),
        _prepare_database_for_open_blocking=mock.Mock(return_value=True),
        _run_startup_message_box=mock.Mock(),
        logger=mock.Mock(),
    )

    selected_path, prepared = profile_session._recover_startup_database_after_failure(
        app,
        failed_path=str(failed_path),
        fallback_paths=[str(failed_path), str(fallback_path), str(recovery_path)],
    )

    assert selected_path == str(fallback_path)
    assert prepared is True
    app._prepare_database_for_open_blocking.assert_called_once_with(
        str(fallback_path),
        title="Open Profile",
        description="Preparing fallback profile database...",
    )
    assert settings.values["db/last_path"] == str(fallback_path)
    assert settings.synced is True
    assert passwords.password_for_database(failed_path) is None
    app._run_startup_message_box.assert_called_once()
    assert (
        "database disk image is malformed" in app._run_startup_message_box.call_args.kwargs["text"]
    )


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
