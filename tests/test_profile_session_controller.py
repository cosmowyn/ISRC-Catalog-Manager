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
    KeyringCredentialError,
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


class _StartupStorageMessageBox:
    def __init__(self, click_label: str = "Migrate Now") -> None:
        self.click_label = click_label
        self.buttons: dict[str, object] = {}
        self.clicked = None

    def addButton(self, label: str, *_args):
        button = object()
        self.buttons[str(label)] = button
        return button

    def setDefaultButton(self, *_args) -> None:
        pass

    def clickedButton(self):
        return self.clicked

    def choose(self) -> None:
        self.clicked = self.buttons.get(self.click_label)


def _storage_layout(tmp_path, *, active_name: str = "active") -> SimpleNamespace:
    return SimpleNamespace(
        portable=False,
        preferred_data_root=tmp_path / "preferred",
        active_data_root=tmp_path / active_name,
    )


def _storage_inspection(
    tmp_path,
    *,
    preferred_state: str = "legacy",
    legacy_root: Path | None = None,
    legacy_items: tuple[str, ...] = ("Database/catalog.db",),
    deferred: bool = False,
    conflict_items: tuple[str, ...] = (),
) -> SimpleNamespace:
    return SimpleNamespace(
        preferred_state=preferred_state,
        legacy_root=legacy_root if legacy_root is not None else tmp_path / "legacy",
        legacy_items=legacy_items,
        deferred=deferred,
        conflict_items=conflict_items,
    )


def test_reconcile_startup_storage_root_handles_resumable_conflict_and_failure(tmp_path):
    preferred = tmp_path / "preferred"
    legacy = tmp_path / "legacy"
    layout = _storage_layout(tmp_path)
    migrate_result = SimpleNamespace(
        action="migrated",
        source_root=legacy,
        target_root=preferred,
        copied_items=["Database/catalog.db"],
    )
    service = mock.Mock(
        inspect=mock.Mock(
            return_value=_storage_inspection(
                tmp_path,
                preferred_state=profile_session.PREFERRED_STATE_RESUMABLE_STAGE,
                legacy_root=legacy,
            )
        ),
        migrate=mock.Mock(return_value=migrate_result),
        defer=mock.Mock(),
    )
    app = SimpleNamespace(
        storage_layout=layout,
        storage_migration_service=service,
        _log_event=mock.Mock(),
    )

    assert profile_session._reconcile_startup_storage_root(app) == preferred.resolve()
    service.migrate.assert_called_once_with()
    app._log_event.assert_called_once()

    service.inspect.return_value = _storage_inspection(
        tmp_path,
        preferred_state=profile_session.PREFERRED_STATE_CONFLICT,
        legacy_root=legacy,
        legacy_items=("Database/catalog.db",),
        conflict_items=("Database/catalog.db",),
    )
    service.migrate.reset_mock()
    assert profile_session._reconcile_startup_storage_root(app) == legacy.resolve()
    service.migrate.assert_not_called()

    service.inspect.return_value = _storage_inspection(
        tmp_path,
        preferred_state=profile_session.PREFERRED_STATE_CONFLICT,
        legacy_root=None,
        legacy_items=(),
        conflict_items=("exports/report.csv",),
    )
    assert profile_session._reconcile_startup_storage_root(app) == preferred.resolve()

    messages: list[_StartupStorageMessageBox] = []

    def run_message_box(**kwargs):
        box = _StartupStorageMessageBox()
        configure = kwargs.get("configure")
        if configure is not None:
            configure(box)
            box.choose()
        messages.append(box)
        return box

    service.inspect.return_value = _storage_inspection(tmp_path, legacy_root=legacy)
    service.migrate.side_effect = RuntimeError("copy failed")
    app._run_startup_message_box = run_message_box

    assert profile_session._reconcile_startup_storage_root(app) == legacy.resolve()
    service.defer.assert_called_with(legacy)
    assert len(messages) == 2


def test_run_storage_layout_migration_reopen_failure_and_background_paths(tmp_path):
    background_app = SimpleNamespace(
        background_tasks=SimpleNamespace(has_running_tasks=mock.Mock(return_value=True))
    )
    with pytest.raises(RuntimeError, match="background tasks"):
        profile_session._run_storage_layout_migration(background_app)

    source_root = tmp_path / "legacy"
    target_root = tmp_path / "preferred"
    db_path = source_root / "Database" / "catalog.db"
    db_path.parent.mkdir(parents=True)
    db_path.write_text("profile", encoding="utf-8")
    failing_service = mock.Mock(
        inspect=mock.Mock(return_value=_storage_inspection(tmp_path, legacy_root=source_root)),
        migrate=mock.Mock(side_effect=RuntimeError("migrate failed")),
    )
    reopen_app = SimpleNamespace(
        background_tasks=SimpleNamespace(has_running_tasks=mock.Mock(return_value=False)),
        storage_migration_service=failing_service,
        current_db_path=str(db_path),
        conn=object(),
        _prepare_for_background_db_task=mock.Mock(),
        _close_database_connection=mock.Mock(),
        open_database=mock.Mock(),
        _reload_profiles_list=mock.Mock(),
    )
    with pytest.raises(RuntimeError, match="migrate failed"):
        profile_session._run_storage_layout_migration(reopen_app)
    reopen_app.open_database.assert_called_once_with(str(db_path))
    reopen_app._reload_profiles_list.assert_called_once_with(select_path=str(db_path))

    missing_target_service = mock.Mock(
        inspect=mock.Mock(return_value=_storage_inspection(tmp_path, legacy_root=source_root)),
        migrate=mock.Mock(
            return_value=SimpleNamespace(
                action="migrated",
                source_root=source_root,
                target_root=target_root,
                copied_items=["Database/catalog.db"],
            )
        ),
    )
    missing_target_app = SimpleNamespace(
        background_tasks=SimpleNamespace(has_running_tasks=mock.Mock(return_value=False)),
        storage_migration_service=missing_target_service,
        current_db_path=str(db_path),
        conn=object(),
        _prepare_for_background_db_task=mock.Mock(),
        _close_database_connection=mock.Mock(),
        _apply_storage_layout=mock.Mock(),
        _configure_logging=mock.Mock(),
        open_database=mock.Mock(),
        _reload_profiles_list=mock.Mock(),
    )
    with pytest.raises(RuntimeError, match="active profile"):
        profile_session._run_storage_layout_migration(missing_target_app)

    no_profile_service = mock.Mock(
        inspect=mock.Mock(return_value=_storage_inspection(tmp_path, legacy_root=source_root)),
        migrate=mock.Mock(
            return_value=SimpleNamespace(
                action="verified",
                source_root=source_root,
                target_root=target_root,
                copied_items=[],
            )
        ),
    )
    no_profile_app = SimpleNamespace(
        background_tasks=SimpleNamespace(has_running_tasks=mock.Mock(return_value=False)),
        storage_migration_service=no_profile_service,
        current_db_path="",
        conn=None,
        _apply_storage_layout=mock.Mock(),
        _configure_logging=mock.Mock(),
        _configure_background_runtime=mock.Mock(),
        _log_event=mock.Mock(),
    )

    result = profile_session._run_storage_layout_migration(no_profile_app)

    assert result.action == "verified"
    no_profile_app._configure_background_runtime.assert_called_once_with()
    no_profile_app._log_event.assert_called_once()


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


def test_on_profile_changed_cancel_and_security_failure_do_not_activate(monkeypatch):
    combo = _Combo()
    combo.addItem("Other", "/profiles/other.db")
    combo.setCurrentIndex(0)
    app = SimpleNamespace(
        profile_combo=combo,
        current_db_path="/profiles/current.db",
        _activate_profile_in_background=mock.Mock(),
    )

    class DeclineMessageBox(_MessageBox):
        @classmethod
        def question(cls, *args):
            cls.messages.append(("question", args))
            return cls.No

    DeclineMessageBox.messages = []
    monkeypatch.setattr(profile_session, "QMessageBox", DeclineMessageBox)
    profile_session._on_profile_changed(app, 0)
    app._activate_profile_in_background.assert_not_called()

    class AcceptMessageBox(_MessageBox):
        messages = []

    monkeypatch.setattr(profile_session, "QMessageBox", AcceptMessageBox)
    monkeypatch.setattr(
        profile_session,
        "_prepare_database_security_for_open",
        mock.Mock(return_value=False),
    )
    profile_session._on_profile_changed(app, 0)
    app._activate_profile_in_background.assert_not_called()


def test_maybe_run_storage_layout_migration_delegates_to_app_reconciler(tmp_path):
    app = SimpleNamespace(_reconcile_startup_storage_root=mock.Mock(return_value=tmp_path))

    assert profile_session._maybe_run_storage_layout_migration(app) == tmp_path
    app._reconcile_startup_storage_root.assert_called_once_with()


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


def test_password_remembering_and_loading_handles_settings_and_keyring_errors(monkeypatch):
    _MessageBox.messages = []
    monkeypatch.setattr(profile_session, "QMessageBox", _MessageBox)
    path = "/profiles/secure.db"
    manager = DatabaseSessionPasswordManager()
    settings = _Settings()
    store = mock.Mock()

    app = SimpleNamespace(
        settings=settings,
        database_passwords=manager,
        database_keyring_credentials=store,
    )

    profile_session._remember_database_password_if_enabled(app, path, "secret-123456")
    store.remember.assert_not_called()
    assert profile_session._load_remembered_database_password(app, path) is None

    settings.values["security/remember_database_password"] = "yes"
    profile_session._remember_database_password_if_enabled(app, path, "secret-123456")
    store.remember.assert_called_once_with(path, "secret-123456")

    store.load.return_value = "remembered-secret-123"
    assert profile_session._load_remembered_database_password(app, path) == "remembered-secret-123"
    assert manager.password_for_database(path) == "remembered-secret-123"

    app.database_keyring_credentials = None
    profile_session._remember_database_password_if_enabled(app, path, "secret-123456")
    assert _MessageBox.messages[-1][0] == "warning"
    assert profile_session._load_remembered_database_password(app, path) is None

    failing_store = mock.Mock(
        remember=mock.Mock(side_effect=KeyringCredentialError("write denied")),
        load=mock.Mock(side_effect=KeyringCredentialError("read denied")),
    )
    app.database_keyring_credentials = failing_store
    profile_session._remember_database_password_if_enabled(app, path, "secret-123456")
    assert _MessageBox.messages[-1][0] == "warning"
    assert profile_session._load_remembered_database_password(app, path) is None
    assert _MessageBox.messages[-1][0] == "warning"


def test_prompt_existing_database_password_retries_invalid_password_and_verifies_unlock(
    monkeypatch,
):
    _MessageBox.messages = []
    monkeypatch.setattr(profile_session, "QMessageBox", _MessageBox)
    monkeypatch.setattr(profile_session, "is_probably_encrypted_database", lambda _path: True)

    class FakeInputDialog:
        results = [
            ("short", True),
            ("valid-secret-123", True),
        ]

        @classmethod
        def getText(cls, *args):
            del args
            return cls.results.pop(0)

    class VerifiedConnection:
        def __init__(self) -> None:
            self.closed = False

        def close(self) -> None:
            self.closed = True

    monkeypatch.setattr(profile_session, "QInputDialog", FakeInputDialog)
    settings = _Settings()
    settings.values["security/remember_database_password"] = True
    manager = DatabaseSessionPasswordManager()
    store = mock.Mock(load=mock.Mock(return_value=None))
    verified_conn = VerifiedConnection()
    app = SimpleNamespace(
        settings=settings,
        database_passwords=manager,
        database_keyring_credentials=store,
        database_security_service=mock.Mock(open=mock.Mock(return_value=verified_conn)),
    )

    assert profile_session._prompt_existing_database_password(app, "/profiles/secure.db") is True

    assert _MessageBox.messages[0][0] == "warning"
    app.database_security_service.open.assert_called_once_with(
        "/profiles/secure.db", "valid-secret-123"
    )
    assert verified_conn.closed is True
    assert manager.password_for_database("/profiles/secure.db") == "valid-secret-123"
    store.remember.assert_called_once_with("/profiles/secure.db", "valid-secret-123")


def test_prompt_existing_database_password_covers_session_remembered_and_cancel_paths(
    monkeypatch,
):
    path = "/profiles/secure.db"
    manager = DatabaseSessionPasswordManager()
    manager.set_password(path, "session-secret-123")
    app = SimpleNamespace(database_passwords=manager, settings=_Settings())

    assert profile_session._prompt_existing_database_password(app, path) is True

    class FakeInputDialog:
        @classmethod
        def getText(cls, *args):
            del args
            return "", False

    monkeypatch.setattr(profile_session, "QInputDialog", FakeInputDialog)
    empty_app = SimpleNamespace(
        database_passwords=DatabaseSessionPasswordManager(), settings=_Settings()
    )
    assert profile_session._prompt_existing_database_password(empty_app, path) is False

    remembered_app = SimpleNamespace(
        database_passwords=DatabaseSessionPasswordManager(),
        settings=_Settings(),
        database_keyring_credentials=mock.Mock(
            load=mock.Mock(return_value="remembered-secret-123")
        ),
    )
    remembered_app.settings.values["security/remember_database_password"] = True
    assert profile_session._prompt_existing_database_password(remembered_app, path) is True


def test_profile_maintenance_backup_path_avoids_existing_backup_and_sidecar(
    monkeypatch,
    tmp_path,
):
    class FakeNow:
        def strftime(self, _fmt):
            return "20260607_120000"

    class FakeDateTime:
        @staticmethod
        def now():
            return FakeNow()

    monkeypatch.setattr(profile_session, "datetime", FakeDateTime)
    app = SimpleNamespace(backups_dir=tmp_path / "backups")
    source = tmp_path / "plain.db"

    first = profile_session._profile_maintenance_backup_path(app, source)
    assert first.name == "plain_unencrypted_20260607_120000.db"
    first.write_text("backup", encoding="utf-8")
    first.with_suffix(".db.backup.json").write_text("{}", encoding="utf-8")

    second = profile_session._profile_maintenance_backup_path(app, source)
    assert second.name == "plain_unencrypted_20260607_120000_1.db"


@pytest.mark.parametrize(
    ("choice", "expected_messages"),
    [
        ("cancel", []),
        ("encrypt", ["critical"]),
    ],
)
def test_plaintext_profile_migration_cancel_and_missing_security_service(
    monkeypatch,
    tmp_path,
    choice,
    expected_messages,
):
    _MessageBox.messages = []
    _ProfileMigrationMessageBox.instances = []
    _ProfileMigrationMessageBox.next_choice = choice
    monkeypatch.setattr(profile_session, "QMessageBox", _ProfileMigrationMessageBox)
    monkeypatch.setattr(profile_session, "QCheckBox", _CheckBox)

    class FakeInputDialog:
        results = [
            ("migration-secret-123", True),
            ("migration-secret-123", True),
        ]

        @classmethod
        def getText(cls, *args):
            del args
            return cls.results.pop(0)

    monkeypatch.setattr(profile_session, "QInputDialog", FakeInputDialog)
    db_path = tmp_path / "plain.db"
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE demo(value TEXT)")
    conn.commit()
    conn.close()

    app = SimpleNamespace(settings=_Settings(), database_security_service=None)

    assert profile_session._migrate_plaintext_profile_if_requested(app, db_path) is False
    assert [message[0] for message in _MessageBox.messages] == expected_messages


def test_plaintext_profile_migration_encrypt_failure_reports_error(monkeypatch, tmp_path):
    _MessageBox.messages = []
    _ProfileMigrationMessageBox.instances = []
    _ProfileMigrationMessageBox.next_choice = "encrypt"
    monkeypatch.setattr(profile_session, "QMessageBox", _ProfileMigrationMessageBox)
    monkeypatch.setattr(profile_session, "QCheckBox", _CheckBox)

    class FakeInputDialog:
        results = [
            ("migration-secret-123", True),
            ("migration-secret-123", True),
        ]

        @classmethod
        def getText(cls, *args):
            del args
            return cls.results.pop(0)

    monkeypatch.setattr(profile_session, "QInputDialog", FakeInputDialog)
    db_path = tmp_path / "plain.db"
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE demo(value TEXT)")
    conn.commit()
    conn.close()
    app = SimpleNamespace(
        settings=_Settings(),
        backups_dir=tmp_path / "backups",
        database_security_service=mock.Mock(
            encrypt_plaintext_database=mock.Mock(side_effect=RuntimeError("encrypt failed"))
        ),
    )

    assert profile_session._migrate_plaintext_profile_if_requested(app, db_path) is False
    assert _MessageBox.messages[-1][0] == "critical"
    assert "encrypt failed" in _MessageBox.messages[-1][1][2]


def test_prepare_database_security_for_open_routes_by_database_type(monkeypatch):
    app = SimpleNamespace()
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(
        profile_session,
        "is_plaintext_sqlite_database",
        lambda path: str(path).endswith("plain.db"),
    )
    monkeypatch.setattr(
        profile_session,
        "is_probably_encrypted_database",
        lambda path: str(path).endswith("secure.db"),
    )
    monkeypatch.setattr(
        profile_session,
        "_migrate_plaintext_profile_if_requested",
        lambda _app, path: calls.append(("plain", str(path))) or False,
    )
    monkeypatch.setattr(
        profile_session,
        "_prompt_existing_database_password",
        lambda _app, path: calls.append(("secure", str(path))) or True,
    )

    assert profile_session._prepare_database_security_for_open(app, "/profiles/plain.db") is False
    assert profile_session._prepare_database_security_for_open(app, "/profiles/secure.db") is True
    assert profile_session._prepare_database_security_for_open(app, "/profiles/new.db") is True
    assert calls == [
        ("plain", "/profiles/plain.db"),
        ("secure", "/profiles/secure.db"),
    ]


def test_change_current_database_password_guardrails_and_failures(monkeypatch):
    _MessageBox.messages = []
    monkeypatch.setattr(profile_session, "QMessageBox", _MessageBox)
    monkeypatch.setattr(
        profile_session, "is_plaintext_sqlite_database", lambda path: path == "plain"
    )
    monkeypatch.setattr(
        profile_session, "is_probably_encrypted_database", lambda path: path == "secure"
    )

    assert (
        profile_session.change_current_database_password(SimpleNamespace(current_db_path=""))
        is False
    )
    assert (
        profile_session.change_current_database_password(SimpleNamespace(current_db_path="plain"))
        is False
    )
    assert (
        profile_session.change_current_database_password(SimpleNamespace(current_db_path="unknown"))
        is False
    )
    assert (
        profile_session.change_current_database_password(
            SimpleNamespace(current_db_path="secure", database_security_service=None)
        )
        is False
    )
    assert [message[0] for message in _MessageBox.messages[-4:]] == [
        "warning",
        "warning",
        "warning",
        "critical",
    ]

    class CancelInputDialog:
        @classmethod
        def getText(cls, *args):
            del args
            return "", False

    monkeypatch.setattr(profile_session, "QInputDialog", CancelInputDialog)
    assert (
        profile_session.change_current_database_password(
            SimpleNamespace(
                current_db_path="secure",
                database_security_service=mock.Mock(),
                database_passwords=DatabaseSessionPasswordManager(),
            )
        )
        is False
    )

    class NewPasswordCancelInputDialog:
        results = [
            ("current-secret-123", True),
            ("", False),
        ]

        @classmethod
        def getText(cls, *args):
            del args
            return cls.results.pop(0)

    security_service = mock.Mock(open=mock.Mock(return_value=mock.Mock(close=mock.Mock())))
    monkeypatch.setattr(profile_session, "QInputDialog", NewPasswordCancelInputDialog)
    assert (
        profile_session.change_current_database_password(
            SimpleNamespace(
                current_db_path="secure",
                database_security_service=security_service,
                database_passwords=DatabaseSessionPasswordManager(),
            )
        )
        is False
    )

    class ChangeFailureInputDialog:
        results = [
            ("current-secret-123", True),
            ("new-secret-123", True),
            ("new-secret-123", True),
        ]

        @classmethod
        def getText(cls, *args):
            del args
            return cls.results.pop(0)

    security_service = mock.Mock(
        open=mock.Mock(return_value=mock.Mock(close=mock.Mock())),
        change_password=mock.Mock(side_effect=RuntimeError("change failed")),
    )
    monkeypatch.setattr(profile_session, "QInputDialog", ChangeFailureInputDialog)
    assert (
        profile_session.change_current_database_password(
            SimpleNamespace(
                current_db_path="secure",
                database_security_service=security_service,
                database_passwords=DatabaseSessionPasswordManager(),
                settings=_Settings(),
            )
        )
        is False
    )
    assert _MessageBox.messages[-1][0] == "critical"


def test_remove_selected_profile_no_choice_and_delete_failure_rolls_back(monkeypatch):
    _MessageBox.messages = []
    monkeypatch.setattr(profile_session, "QMessageBox", _MessageBox)
    monkeypatch.setattr(
        profile_session, "_prompt_profile_removal_choice", mock.Mock(return_value=None)
    )
    app = SimpleNamespace()

    profile_session.remove_selected_profile(app)

    monkeypatch.setattr(
        profile_session,
        "_prompt_profile_removal_choice",
        mock.Mock(return_value="/profiles/current.db"),
    )
    app = SimpleNamespace(
        current_db_path="/profiles/current.db",
        session_history_manager=SimpleNamespace(
            capture_profile_snapshot=mock.Mock(return_value="/snap/current.zip"),
        ),
        _close_database_connection=mock.Mock(),
        profile_workflows=SimpleNamespace(
            delete_profile=mock.Mock(side_effect=RuntimeError("delete failed"))
        ),
        conn=SimpleNamespace(rollback=mock.Mock()),
        logger=mock.Mock(),
    )

    profile_session.remove_selected_profile(app)

    app._close_database_connection.assert_called_once()
    app.conn.rollback.assert_called_once()
    app.logger.exception.assert_called_once()
    assert _MessageBox.messages[-1][0] == "critical"


def test_prepare_database_session_initializes_schema_and_always_closes(monkeypatch):
    progress = []
    session = SimpleNamespace(conn=mock.Mock(), cursor=mock.Mock())
    database_session = SimpleNamespace(
        open=mock.Mock(return_value=session),
        close=mock.Mock(),
    )
    schema_instances = []

    class FakeSchemaService:
        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs
            self.init_db = mock.Mock()
            self.migrate_schema = mock.Mock()
            schema_instances.append(self)

    monkeypatch.setattr(profile_session, "DatabaseSchemaService", FakeSchemaService)
    app = SimpleNamespace(
        database_session=database_session,
        logger=mock.Mock(),
        data_root="/data",
        _background_schema_audit_callback=mock.Mock(return_value=mock.Mock()),
    )

    assert (
        profile_session._prepare_database_session(
            app,
            "/profiles/demo.db",
            progress_callback=lambda *args: progress.append(args),
        )
        == "/profiles/demo.db"
    )

    database_session.open.assert_called_once_with("/profiles/demo.db")
    database_session.close.assert_called_once_with(session.conn)
    schema_instances[0].init_db.assert_called_once()
    schema_instances[0].migrate_schema.assert_called_once()
    assert progress == [
        (1, 4, "Opening profile database session..."),
        (2, 4, "Initializing required database tables..."),
        (3, 4, "Applying schema migrations and checks..."),
        (4, 4, "Profile database prepared."),
    ]


def test_prepare_database_session_closes_connection_when_schema_migration_fails(monkeypatch):
    session = SimpleNamespace(conn=mock.Mock(), cursor=mock.Mock())
    database_session = SimpleNamespace(
        open=mock.Mock(return_value=session),
        close=mock.Mock(),
    )

    class FailingSchemaService:
        def __init__(self, *args, **kwargs):
            del args, kwargs

        def init_db(self):
            return None

        def migrate_schema(self):
            raise RuntimeError("migration failed")

    monkeypatch.setattr(profile_session, "DatabaseSchemaService", FailingSchemaService)
    app = SimpleNamespace(
        database_session=database_session,
        logger=mock.Mock(),
        data_root="/data",
        _background_schema_audit_callback=mock.Mock(return_value=mock.Mock()),
    )

    with pytest.raises(RuntimeError, match="migration failed"):
        profile_session._prepare_database_session(app, "/profiles/demo.db")
    database_session.close.assert_called_once_with(session.conn)


def test_startup_recovery_candidates_deduplicate_failures_and_create_recovery_path(
    monkeypatch,
    tmp_path,
):
    class FakeNow:
        def strftime(self, _fmt):
            return "20260607_120000"

    class FakeDateTime:
        @staticmethod
        def now():
            return FakeNow()

    monkeypatch.setattr(profile_session, "datetime", FakeDateTime)
    failed = tmp_path / "failed.db"
    fallback = tmp_path / "fallback.db"
    app = SimpleNamespace(
        database_dir=tmp_path,
        profile_store=SimpleNamespace(
            list_profiles=mock.Mock(side_effect=RuntimeError("profile list unavailable"))
        ),
    )

    candidates = profile_session._startup_profile_recovery_candidates(
        app,
        failed_paths=[str(failed), str(tmp_path / profile_session.STARTUP_RECOVERY_PROFILE_NAME)],
        fallback_paths=[failed, fallback, fallback, None],
    )

    assert candidates == [
        str(fallback),
        str(tmp_path / "startup_recovery_20260607_120000_1.db"),
    ]


def test_recover_startup_database_after_failure_skips_locked_and_failed_candidates(
    monkeypatch,
    tmp_path,
):
    encrypted = tmp_path / "encrypted.db"
    broken = tmp_path / "broken.db"
    recovery = tmp_path / "recovery.db"
    monkeypatch.setattr(
        profile_session,
        "_startup_profile_recovery_candidates",
        mock.Mock(return_value=[str(encrypted), str(broken), str(recovery)]),
    )
    monkeypatch.setattr(
        profile_session,
        "is_probably_encrypted_database",
        lambda path: Path(path) == encrypted,
    )
    monkeypatch.setattr(
        profile_session,
        "_prepare_database_security_for_open",
        mock.Mock(return_value=False),
    )
    passwords = DatabaseSessionPasswordManager()
    passwords.set_password(encrypted, "locked-secret-123")
    passwords.set_password(broken, "broken-secret-123")
    app = SimpleNamespace(
        settings=None,
        database_passwords=passwords,
        _prepare_database_for_open_blocking=mock.Mock(side_effect=[False, True]),
        _run_startup_message_box=mock.Mock(),
        logger=mock.Mock(),
    )

    selected, prepared = profile_session._recover_startup_database_after_failure(
        app,
        failed_path=str(tmp_path / "failed.db"),
        fallback_paths=[],
        failure_reason="startup failed",
    )

    assert (selected, prepared) == (str(recovery), True)
    profile_session._prepare_database_security_for_open.assert_called_once_with(app, str(encrypted))
    assert app._prepare_database_for_open_blocking.call_args_list == [
        mock.call(
            str(broken),
            title="Open Profile",
            description="Preparing fallback profile database...",
        ),
        mock.call(
            str(recovery),
            title="Open Profile",
            description="Preparing fallback profile database...",
        ),
    ]
    assert passwords.password_for_database(encrypted) == "locked-secret-123"
    assert passwords.password_for_database(broken) is None


def test_open_database_schema_prepared_wires_services_and_progress():
    progress = []
    session = SimpleNamespace(conn=mock.Mock(), cursor=mock.Mock())
    database_session = SimpleNamespace(
        open=mock.Mock(return_value=session),
        remember_last_path=mock.Mock(),
    )
    app = SimpleNamespace(
        conn=None,
        cursor=None,
        database_passwords=DatabaseSessionPasswordManager(),
        database_session=database_session,
        _configure_background_runtime=mock.Mock(),
        _report_startup_phase=mock.Mock(),
        _init_services=mock.Mock(),
        _migrate_artist_code_from_qsettings_if_needed=mock.Mock(),
        load_artist_code=mock.Mock(return_value="AB1"),
        _log_event=mock.Mock(),
        settings=_Settings(),
        logger=mock.Mock(),
        _migrate_legacy_owner_party_if_needed=mock.Mock(),
        _sync_application_isrc_registry=mock.Mock(),
        _load_blob_icon_settings=mock.Mock(return_value={"color": "blue"}),
        load_active_custom_fields=mock.Mock(return_value=["field"]),
        _refresh_catalog_workspace_docks=mock.Mock(),
        _audit=mock.Mock(),
        _audit_commit=mock.Mock(),
        _refresh_history_actions=mock.Mock(),
        _current_auto_snapshot_marker=mock.Mock(return_value=42),
        _refresh_auto_snapshot_schedule=mock.Mock(),
    )

    profile_session.open_database(
        app,
        "/profiles/demo.db",
        schema_prepared=True,
        progress_callback=lambda *args: progress.append(args),
    )

    assert app.conn is session.conn
    assert app.cursor is session.cursor
    assert app.current_db_path == "/profiles/demo.db"
    database_session.remember_last_path.assert_called_once_with(app.settings, "/profiles/demo.db")
    app._init_services.assert_called_once()
    app._audit.assert_called_once_with(
        "PROFILE", "Database", ref_id="/profiles/demo.db", details="open_database()"
    )
    assert app.blob_icon_settings == {"color": "blue"}
    assert app.active_custom_fields == ["field"]
    assert app._last_auto_snapshot_marker == 42
    assert progress == [
        (1, 6, "Opened profile database connection."),
        (2, 6, "Configured background runtime services."),
        (3, 6, "Loaded profile service layer."),
        (4, 6, "Restored migrated profile settings."),
        (5, 6, "Loaded profile metadata and refreshed workspace shells."),
        (6, 6, "Profile database ready for catalog loading."),
    ]


def test_activate_profile_refreshes_shell_after_opening_database():
    class SuspendHistory:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    app = SimpleNamespace(
        _save_header_state=mock.Mock(side_effect=RuntimeError("ignore save failure")),
        open_database=mock.Mock(),
        _reset_catalog_zoom_for_profile_change=mock.Mock(),
        _suspend_table_layout_history=mock.Mock(return_value=SuspendHistory()),
        load_active_custom_fields=mock.Mock(return_value=["field"]),
        _rebuild_table_headers=mock.Mock(),
        _load_header_state=mock.Mock(side_effect=RuntimeError("ignore header failure")),
        _reload_profiles_list=mock.Mock(),
        refresh_table_preserve_view=mock.Mock(),
        populate_all_comboboxes=mock.Mock(),
        _update_add_data_generated_fields=mock.Mock(),
        _refresh_history_actions=mock.Mock(),
        _schedule_owner_party_bootstrap=mock.Mock(),
    )

    profile_session._activate_profile(app, "/profiles/demo.db")

    app.open_database.assert_called_once_with("/profiles/demo.db")
    app._reset_catalog_zoom_for_profile_change.assert_called_once()
    assert app.active_custom_fields == ["field"]
    app._reload_profiles_list.assert_called_once_with(select_path="/profiles/demo.db")
    app._schedule_owner_party_bootstrap.assert_called_once()
