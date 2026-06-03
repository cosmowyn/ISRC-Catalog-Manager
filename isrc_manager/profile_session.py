"""Profile, storage-root, and database-session orchestration for App."""

from __future__ import annotations

import json
import logging
import traceback
from datetime import datetime
from pathlib import Path

from PySide6.QtWidgets import QCheckBox, QFileDialog, QInputDialog, QLineEdit, QMessageBox

from isrc_manager.conversion import ConversionService
from isrc_manager.isrc_registry import ApplicationISRCRegistryService
from isrc_manager.paths import resolve_app_storage_layout
from isrc_manager.services import DatabaseSchemaService
from isrc_manager.services.database_security import (
    DatabasePasswordPolicyError,
    InvalidDatabasePasswordError,
    KeyringCredentialError,
    is_plaintext_sqlite_database,
    is_probably_encrypted_database,
    validate_database_password,
)
from isrc_manager.startup_progress import StartupPhase, StartupProgressTracker
from isrc_manager.storage_migration import (
    PREFERRED_STATE_CONFLICT,
    PREFERRED_STATE_RESUMABLE_STAGE,
    PREFERRED_STATE_VALID_COMPLETE,
    StorageMigrationService,
)
from isrc_manager.tasks import TaskFailure

SUPPRESS_UNENCRYPTED_PROFILE_WARNING_SETTING = "security/suppress_unencrypted_profile_warning"
BACKUP_SIDECAR_SUFFIX = ".backup.json"


def _apply_storage_layout(app, *, active_data_root: str | Path | None = None) -> None:
    app._report_storage_startup_progress(86, 100, "Applying active storage root...")
    app.storage_layout = resolve_app_storage_layout(
        settings=app.settings,
        active_data_root=active_data_root,
    )
    app.storage_migration_service = StorageMigrationService(
        app.storage_layout,
        settings=app.settings,
        reporter=app._log_event,
        progress_reporter=app._report_storage_startup_progress,
    )
    app.data_root = app.storage_layout.data_root
    app.database_dir = app.storage_layout.database_dir
    app.exports_dir = app.storage_layout.exports_dir
    app.logs_dir = app.storage_layout.logs_dir
    app.backups_dir = app.storage_layout.backups_dir
    app.history_dir = app.storage_layout.history_dir
    app.help_dir = app.storage_layout.help_dir

    storage_directories = (
        app.data_root,
        app.database_dir,
        app.exports_dir,
        app.logs_dir,
        app.backups_dir,
        app.history_dir,
        app.help_dir,
    )
    for directory_index, directory in enumerate(storage_directories, start=1):
        app._report_storage_startup_progress(
            86 + int((directory_index / len(storage_directories)) * 10),
            100,
            f"Ensuring storage folder: {directory.name}",
        )
        directory.mkdir(parents=True, exist_ok=True)

    today_stamp = datetime.now().strftime("%Y-%m-%d")
    app.log_path = app.logs_dir / f"isrc_manager_{today_stamp}.log"
    app.trace_log_path = app.logs_dir / f"isrc_manager_trace_{today_stamp}.jsonl"
    app.help_file_path = app.help_dir / "isrc_catalog_manager_help.html"
    factory = getattr(app, "background_service_factory", None)
    if factory is not None:
        factory.configure(
            data_root=app.data_root,
            history_dir=app.history_dir,
            backups_dir=app.backups_dir,
            settings_path=app.settings.fileName(),
        )
    registry = getattr(app, "application_isrc_registry", None)
    if registry is not None:
        app.application_isrc_registry = ApplicationISRCRegistryService(app.data_root)
        app.application_isrc_registry.ensure_schema()


def _reconcile_startup_storage_root(app) -> Path:
    inspection = app.storage_migration_service.inspect()
    preferred_root = app.storage_layout.preferred_data_root.resolve()
    if app.storage_layout.portable:
        app._log_event(
            "storage.migration.startup",
            "Portable mode is active; storage migration is skipped",
            data_root=preferred_root,
        )
        return preferred_root

    if inspection.preferred_state == PREFERRED_STATE_VALID_COMPLETE:
        result = app.storage_migration_service.migrate()
        app._log_event(
            "storage.migration.startup",
            "Adopted verified preferred app-data root during startup",
            action=result.action,
            source_root=result.source_root,
            target_root=result.target_root,
        )
        return result.target_root.resolve()

    if inspection.preferred_state == PREFERRED_STATE_RESUMABLE_STAGE:
        result = app.storage_migration_service.migrate()
        app._log_event(
            "storage.migration.startup",
            "Resumed staged app-data migration during startup",
            action=result.action,
            source_root=result.source_root,
            target_root=result.target_root,
        )
        return result.target_root.resolve()

    if inspection.preferred_state == PREFERRED_STATE_CONFLICT:
        app._log_event(
            "storage.migration.startup_conflict",
            "Preferred app-data root contains conflicting content; keeping the current managed root",
            level=logging.WARNING,
            preferred_root=preferred_root,
            conflict_items=list(inspection.conflict_items),
        )
        if inspection.legacy_root is not None and inspection.legacy_items:
            return inspection.legacy_root.resolve()
        return preferred_root

    if inspection.legacy_root is None or not inspection.legacy_items:
        app._log_event(
            "storage.migration.startup",
            "No legacy app-data migration is needed on startup",
            active_root=preferred_root,
            preferred_state=inspection.preferred_state,
        )
        return preferred_root

    if inspection.deferred and app.storage_layout.active_data_root == inspection.legacy_root:
        app._log_event(
            "storage.migration.startup_deferred",
            "Startup is honoring the deferred legacy app-data root",
            legacy_root=inspection.legacy_root,
        )
        return inspection.legacy_root.resolve()

    lines = [
        "A legacy app-data folder was found.",
        "",
        f"Current folder: {inspection.legacy_root}",
        f"New folder: {app.storage_layout.preferred_data_root}",
        "",
        "The migration will copy app-owned profiles, history, backups, logs, exports, help files, and managed media into the new app folder.",
        "Legacy data will stay in place until you choose to remove it later.",
        "",
        "Migrate to the new app folder now?",
    ]
    migrate_button = None
    keep_button = None

    def _configure_message_box(message_box) -> None:
        nonlocal migrate_button, keep_button
        migrate_button = message_box.addButton("Migrate Now", QMessageBox.AcceptRole)
        keep_button = message_box.addButton(
            "Keep Current Folder For Now",
            QMessageBox.RejectRole,
        )
        if hasattr(message_box, "setDefaultButton"):
            message_box.setDefaultButton(migrate_button)

    message_box = app._run_startup_message_box(
        title="App Data Migration",
        icon=QMessageBox.Warning,
        text="\n".join(lines),
        configure=_configure_message_box,
    )

    if message_box.clickedButton() is keep_button:
        app.storage_migration_service.defer(inspection.legacy_root)
        app._log_event(
            "storage.migration.deferred",
            "Startup app-data migration was deferred by the user",
            legacy_root=inspection.legacy_root,
            preferred_root=preferred_root,
        )
        return inspection.legacy_root.resolve()

    try:
        result = app.storage_migration_service.migrate()
    except Exception as exc:
        app.storage_migration_service.defer(inspection.legacy_root)
        app._log_event(
            "storage.migration.startup_failed",
            "Startup app-data migration could not be completed; continuing with the legacy root",
            level=logging.WARNING,
            legacy_root=inspection.legacy_root,
            preferred_root=preferred_root,
            error=str(exc),
        )
        app._run_startup_message_box(
            title="App Data Migration",
            icon=QMessageBox.Warning,
            text=(
                "The app-data migration could not be completed.\n\n"
                f"{exc}\n\nThe app will continue to use the current folder for now."
            ),
        )
        return inspection.legacy_root.resolve()

    app._run_startup_message_box(
        title="App Data Migration",
        icon=QMessageBox.Information,
        text=(
            f"App-owned data was {result.action} successfully.\n\n"
            f"Items: {', '.join(result.copied_items)}"
        ),
    )
    app._log_event(
        "storage.migration.startup",
        "Startup selected the preferred app-data root after migration",
        action=result.action,
        source_root=result.source_root,
        target_root=result.target_root,
    )
    return result.target_root.resolve()


def _maybe_run_storage_layout_migration(app) -> Path:
    return app._reconcile_startup_storage_root()


def _run_storage_layout_migration(app):
    if hasattr(app, "background_tasks") and app.background_tasks.has_running_tasks():
        raise RuntimeError(
            "Finish any running background tasks before migrating app-owned storage."
        )

    inspection = app.storage_migration_service.inspect()
    source_root = inspection.legacy_root.resolve() if inspection.legacy_root is not None else None
    previous_current_path = str(getattr(app, "current_db_path", "") or "").strip()
    previous_was_open = getattr(app, "conn", None) is not None

    if previous_was_open:
        app._prepare_for_background_db_task()
        app._close_database_connection()

    try:
        result = app.storage_migration_service.migrate()
    except Exception:
        if previous_was_open and previous_current_path and Path(previous_current_path).exists():
            app.open_database(previous_current_path)
            app._reload_profiles_list(select_path=previous_current_path)
        raise

    source_root = result.source_root.resolve()
    target_root = result.target_root.resolve()

    app._apply_storage_layout(active_data_root=target_root)
    app._configure_logging()

    if previous_was_open and previous_current_path:
        reopened_path = previous_current_path
        try:
            relative = Path(previous_current_path).resolve().relative_to(source_root)
        except Exception:
            relative = None
        if relative is not None:
            migrated_path = (target_root / relative).resolve()
            if not migrated_path.exists():
                raise RuntimeError(
                    "The active profile did not appear in the migrated app-data folder."
                )
            reopened_path = str(migrated_path)
        app.open_database(reopened_path)
        app._reload_profiles_list(select_path=reopened_path)
    else:
        app._configure_background_runtime()

    app._log_event(
        "storage.migration",
        "Completed app-owned storage recovery",
        source_root=source_root,
        target_root=target_root,
        action=result.action,
        migrated_items=list(result.copied_items),
    )
    return result


def _reload_profiles_list(app, select_path: str | None = None):
    app.profile_combo.blockSignals(True)
    app.profile_combo.clear()
    current_path = getattr(app, "current_db_path", None)
    for choice in app.profile_workflows.list_profile_choices(current_db_path=current_path):
        app.profile_combo.addItem(choice.label, choice.path)
    if select_path:
        idx = app.profile_combo.findData(select_path)
        if idx >= 0:
            app.profile_combo.setCurrentIndex(idx)
    app.profile_combo.blockSignals(False)


def _on_profile_changed(app, idx: int):
    if idx < 0:
        return
    path = app.profile_combo.itemData(idx)
    if not path or path == app.current_db_path:
        return
    if (
        QMessageBox.question(
            app,
            "Switch Profile",
            f"Switch to database:\n{path}?",
            QMessageBox.Yes | QMessageBox.No,
        )
        != QMessageBox.Yes
    ):
        return
    if not _prepare_database_security_for_open(app, path):
        return

    previous_path = app.current_db_path

    def _after_switch(prepared_path: str):
        app._log_event(
            "profile.switch",
            "Switched profile",
            from_path=previous_path,
            to_path=prepared_path,
        )
        app._audit("PROFILE", "Database", ref_id=prepared_path, details="switch_profile")
        app._audit_commit()
        app.session_history_manager.record_profile_switch(
            from_path=previous_path,
            to_path=prepared_path,
            action_type="profile.switch",
        )
        app._refresh_history_actions()

    app._activate_profile_in_background(
        path,
        title="Switch Profile",
        description="Preparing the selected profile database...",
        on_activated=_after_switch,
    )


def _settings_bool(app, key: str, default: bool = False) -> bool:
    settings = getattr(app, "settings", None)
    if settings is None:
        return default
    raw = settings.value(key, default)
    if isinstance(raw, bool):
        return raw
    return str(raw).strip().lower() not in {"", "0", "false", "no", "off"}


def _remember_database_password_enabled(app) -> bool:
    return _settings_bool(app, "security/remember_database_password", False)


def _unencrypted_profile_warning_suppressed(app) -> bool:
    return _settings_bool(app, SUPPRESS_UNENCRYPTED_PROFILE_WARNING_SETTING, False)


def _set_unencrypted_profile_warning_suppressed(app, enabled: bool) -> None:
    settings = getattr(app, "settings", None)
    if settings is None:
        return
    settings.setValue(SUPPRESS_UNENCRYPTED_PROFILE_WARNING_SETTING, bool(enabled))
    sync = getattr(settings, "sync", None)
    if callable(sync):
        sync()


def _database_password_manager(app):
    return getattr(app, "database_passwords", None)


def _database_security_service(app):
    return getattr(app, "database_security_service", None)


def _database_keyring_store(app):
    return getattr(app, "database_keyring_credentials", None)


def _set_session_database_password(app, path: str | Path, password: str) -> None:
    manager = _database_password_manager(app)
    if manager is not None:
        manager.set_password(path, password)


def _forget_session_database_password(app, path: str | Path) -> None:
    manager = _database_password_manager(app)
    if manager is not None:
        manager.forget_password(path)


def _session_database_password(app, path: str | Path) -> str | None:
    manager = _database_password_manager(app)
    if manager is None:
        return None
    return manager.password_for_database(path)


def _remember_database_password_if_enabled(app, path: str | Path, password: str) -> None:
    if not _remember_database_password_enabled(app):
        return
    store = _database_keyring_store(app)
    if store is None:
        QMessageBox.warning(
            app,
            "Database Password",
            "The OS keychain/keyring is not available, so this password was kept for this app session only.",
        )
        return
    try:
        store.remember(path, password)
    except KeyringCredentialError as exc:
        QMessageBox.warning(app, "Database Password", str(exc))


def _load_remembered_database_password(app, path: str | Path) -> str | None:
    if not _remember_database_password_enabled(app):
        return None
    store = _database_keyring_store(app)
    if store is None:
        return None
    try:
        password = store.load(path)
    except KeyringCredentialError as exc:
        QMessageBox.warning(app, "Database Password", str(exc))
        return None
    if password:
        _set_session_database_password(app, path, password)
    return password


def _prompt_password_text(app, *, title: str, label: str) -> str | None:
    password, accepted = QInputDialog.getText(
        app,
        title,
        label,
        QLineEdit.Password,
    )
    if not accepted:
        return None
    return str(password or "")


def _prompt_existing_database_password(app, path: str | Path) -> bool:
    if _session_database_password(app, path):
        return True
    remembered = _load_remembered_database_password(app, path)
    if remembered:
        return True
    security_service = _database_security_service(app)
    while True:
        password = _prompt_password_text(
            app,
            title="Unlock Profile",
            label=f"Password for encrypted profile:\n{path}",
        )
        if password is None:
            return False
        try:
            clean_password = validate_database_password(password)
        except DatabasePasswordPolicyError as exc:
            QMessageBox.warning(app, "Invalid Password", str(exc))
            continue
        if security_service is not None and is_probably_encrypted_database(path):
            try:
                conn = security_service.open(path, clean_password)
                conn.close()
            except InvalidDatabasePasswordError as exc:
                QMessageBox.warning(app, "Unlock Failed", str(exc))
                continue
            except Exception as exc:
                QMessageBox.critical(
                    app,
                    "Unlock Failed",
                    f"Could not unlock the encrypted profile:\n{exc}",
                )
                return False
        _set_session_database_password(app, path, clean_password)
        _remember_database_password_if_enabled(app, path, clean_password)
        return True


def _prompt_new_database_password(app, *, title: str) -> str | None:
    while True:
        password = _prompt_password_text(
            app,
            title=title,
            label=(
                "Choose a database password. It protects the profile and backups if the "
                "database file is copied or stolen."
            ),
        )
        if password is None:
            return None
        confirmation = _prompt_password_text(
            app,
            title=title,
            label="Confirm the database password:",
        )
        if confirmation is None:
            return None
        try:
            return validate_database_password(password, confirmation=confirmation)
        except DatabasePasswordPolicyError as exc:
            QMessageBox.warning(app, "Invalid Password", str(exc))


def _profile_maintenance_backup_path(app, source_path: str | Path) -> Path:
    source = Path(source_path)
    backups_dir = Path(getattr(app, "backups_dir", source.parent))
    backups_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    stem = source.stem or "profile"
    candidate = backups_dir / f"{stem}_unencrypted_{timestamp}.db"
    counter = 1
    while (
        candidate.exists()
        or candidate.with_suffix(candidate.suffix + BACKUP_SIDECAR_SUFFIX).exists()
    ):
        candidate = backups_dir / f"{stem}_unencrypted_{timestamp}_{counter}.db"
        counter += 1
    return candidate


def _write_profile_maintenance_backup_sidecar(
    backup_path: str | Path,
    *,
    source_db_path: str | Path,
    kind: str,
    label: str,
) -> None:
    backup = Path(backup_path)
    payload = {
        "backup_id": None,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "kind": kind,
        "label": label,
        "source_db_path": str(source_db_path),
        "metadata": {"source": "profile_maintenance"},
    }
    sidecar_path = backup.with_suffix(backup.suffix + BACKUP_SIDECAR_SUFFIX)
    sidecar_path.parent.mkdir(parents=True, exist_ok=True)
    sidecar_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _migrate_plaintext_profile_if_requested(app, path: str | Path) -> bool:
    if not is_plaintext_sqlite_database(path):
        return True
    if _unencrypted_profile_warning_suppressed(app):
        return True

    message_box = QMessageBox(app)
    message_box.setIcon(QMessageBox.Warning)
    message_box.setWindowTitle("Unencrypted Profile")
    message_box.setText("This profile is an unencrypted SQLite database.")
    message_box.setInformativeText(
        "Encrypted SQLCipher profiles protect catalog data and backups if the database file is "
        "copied or stolen. You can encrypt this profile now, or open it unencrypted for this "
        "session."
    )
    encrypt_button = message_box.addButton("Encrypt Now", QMessageBox.AcceptRole)
    open_button = message_box.addButton("Open Unencrypted", QMessageBox.DestructiveRole)
    cancel_button = message_box.addButton(QMessageBox.Cancel)
    suppress_check = QCheckBox("Do not warn again when I open unencrypted profiles")
    message_box.setCheckBox(suppress_check)
    message_box.setDefaultButton(encrypt_button)
    message_box.exec()
    clicked_button = message_box.clickedButton()
    if clicked_button is cancel_button:
        return False
    if clicked_button is open_button:
        if suppress_check.isChecked():
            _set_unencrypted_profile_warning_suppressed(app, True)
        return True

    password = _prompt_new_database_password(app, title="Encrypt Profile")
    if password is None:
        return False
    security_service = _database_security_service(app)
    if security_service is None:
        QMessageBox.critical(
            app,
            "Encrypt Profile",
            "SQLCipher database security service is not available.",
        )
        return False
    try:
        backup_path = _profile_maintenance_backup_path(app, path)
        result = security_service.encrypt_plaintext_database(
            path,
            password,
            backup_path=backup_path,
        )
    except Exception as exc:
        QMessageBox.critical(app, "Encrypt Profile", f"Could not encrypt this profile:\n{exc}")
        return False
    try:
        _write_profile_maintenance_backup_sidecar(
            result.backup_path,
            source_db_path=path,
            kind="profile_migration_unencrypted",
            label=f"Pre-encryption backup: {Path(path).name}",
        )
    except Exception as exc:
        QMessageBox.warning(
            app,
            "Encrypt Profile",
            f"Profile encrypted, but backup metadata could not be written:\n{exc}",
        )
    _set_session_database_password(app, path, password)
    _remember_database_password_if_enabled(app, path, password)
    QMessageBox.information(
        app,
        "Profile Encrypted",
        f"Encrypted profile:\n{result.database_path}\n\nUnencrypted backup:\n{result.backup_path}",
    )
    return True


def _prepare_database_security_for_open(app, path: str | Path) -> bool:
    if is_plaintext_sqlite_database(path):
        return _migrate_plaintext_profile_if_requested(app, path)
    if is_probably_encrypted_database(path):
        return _prompt_existing_database_password(app, path)
    return True


def change_current_database_password(app) -> bool:
    path = str(getattr(app, "current_db_path", "") or "").strip()
    if not path:
        QMessageBox.warning(app, "Database Password", "Open a profile first.")
        return False
    if is_plaintext_sqlite_database(path):
        QMessageBox.warning(
            app,
            "Database Password",
            "This profile is not encrypted yet. Open it through the profile picker to run migration first.",
        )
        return False
    if not is_probably_encrypted_database(path):
        QMessageBox.warning(
            app,
            "Database Password",
            "This profile is empty or cannot be identified as an encrypted database.",
        )
        return False
    security_service = _database_security_service(app)
    if security_service is None:
        QMessageBox.critical(
            app,
            "Database Password",
            "SQLCipher database security service is not available.",
        )
        return False

    current_password = _prompt_password_text(
        app,
        title="Change Database Password",
        label="Current database password:",
    )
    if current_password is None:
        return False
    try:
        validate_database_password(current_password)
        verify_conn = security_service.open(path, current_password)
        verify_conn.close()
    except Exception as exc:
        QMessageBox.warning(
            app, "Database Password", f"Current password could not unlock the profile:\n{exc}"
        )
        return False

    new_password = _prompt_new_database_password(app, title="Change Database Password")
    if new_password is None:
        return False
    try:
        security_service.change_password(path, current_password, new_password)
    except Exception as exc:
        QMessageBox.critical(
            app, "Database Password", f"Could not change the database password:\n{exc}"
        )
        return False
    _set_session_database_password(app, path, new_password)
    _remember_database_password_if_enabled(app, path, new_password)
    QMessageBox.information(app, "Database Password", "Database password changed.")
    return True


def create_new_profile(app):
    name, ok = QInputDialog.getText(
        app, "New Profile", "Database file name (no path, e.g., mylabel.db):"
    )
    if not ok or not name.strip():
        return
    previous_path = app.current_db_path
    try:
        new_path = str(app.profile_workflows.build_new_profile_path(name))
    except FileExistsError:
        QMessageBox.warning(app, "Exists", "A database with this name already exists.")
        return
    password = _prompt_new_database_password(app, title="New Profile Password")
    if password is None:
        return
    _set_session_database_password(app, new_path, password)
    app._clear_table_settings_for_path(new_path)

    def _after_create(prepared_path: str):
        app._log_event(
            "profile.create",
            "Created new profile database",
            previous_path=previous_path,
            created_path=prepared_path,
        )
        app._audit("PROFILE", "Database", ref_id=prepared_path, details="create_new_profile")
        app._audit_commit()
        app.session_history_manager.record_profile_create(
            created_path=prepared_path,
            previous_path=previous_path,
        )
        app._refresh_history_actions()
        _remember_database_password_if_enabled(app, prepared_path, password)
        QMessageBox.information(app, "Profile Created", f"Database created:\n{prepared_path}")

    app._activate_profile_in_background(
        new_path,
        title="Create Profile",
        description="Creating the new profile database...",
        on_activated=_after_create,
    )


def browse_profile(app):
    path, _ = QFileDialog.getOpenFileName(
        app, "Open Database", str(app.database_dir), "SQLite DB (*.db);;All Files (*)"
    )
    if not path:
        return
    if not _prepare_database_security_for_open(app, path):
        return
    previous_path = app.current_db_path

    def _after_browse(prepared_path: str):
        app._log_event(
            "profile.browse",
            "Opened external profile database",
            previous_path=previous_path,
            path=prepared_path,
        )
        app._audit("PROFILE", "Database", ref_id=prepared_path, details="browse_profile")
        app._audit_commit()
        app.session_history_manager.record_profile_switch(
            from_path=previous_path,
            to_path=prepared_path,
            action_type="profile.browse",
            label=f"Browse Profile: {Path(prepared_path).name}",
        )
        app._refresh_history_actions()

    app._activate_profile_in_background(
        path,
        title="Open Profile",
        description="Preparing the selected profile database...",
        on_activated=_after_browse,
    )


def remove_selected_profile(app):
    idx = app.profile_combo.currentIndex()
    if idx < 0:
        return
    path = app.profile_combo.itemData(idx)
    if not path:
        return

    if (
        QMessageBox.question(
            app,
            "Remove Profile",
            f"Delete this database file from disk?\n\n{path}\n\nThis cannot be undone.",
            QMessageBox.Yes | QMessageBox.No,
        )
        != QMessageBox.Yes
    ):
        return

    deleting_current = getattr(app, "current_db_path", None) == path
    current_path = app.current_db_path
    removed_snapshot_path = None

    try:
        removed_snapshot_path = app.session_history_manager.capture_profile_snapshot(
            path,
            kind="profile_remove",
        )
        if deleting_current:
            app._close_database_connection()

        result = app.profile_workflows.delete_profile(path, getattr(app, "current_db_path", None))
        app._sync_application_isrc_registry()

        app._reload_profiles_list(select_path=None)

        if result.deleting_current and result.fallback_path:
            app.open_database(result.fallback_path)
            app._reload_profiles_list(select_path=result.fallback_path)
            app._schedule_owner_party_bootstrap()

        app.refresh_table_preserve_view()
        app.populate_all_comboboxes()
        app._log_event(
            "profile.remove",
            "Removed profile database from disk",
            level=logging.WARNING,
            path=path,
            deleting_current=result.deleting_current,
            fallback_path=result.fallback_path,
        )
        app._audit("PROFILE", "Database", ref_id=path, details="remove_profile")
        app._audit_commit()
        app.session_history_manager.record_profile_remove(
            deleted_path=path,
            current_path=current_path,
            fallback_path=result.fallback_path,
            deleting_current=result.deleting_current,
            snapshot_path=removed_snapshot_path,
        )
        app._refresh_history_actions()
        QMessageBox.information(app, "Profile Removed", f"Deleted:\n{path}")
    except Exception as e:
        if hasattr(app, "conn") and app.conn:
            app.conn.rollback()
        app.logger.exception(f"Remove profile failed: {e}")
        QMessageBox.critical(app, "Remove Error", f"Could not delete the database:\n{e}")


def _close_database_connection(app):
    app._stop_audio_waveform_cache_worker(wait=False)
    closing_path = getattr(app, "current_db_path", None)
    if hasattr(app, "auto_snapshot_timer"):
        app.auto_snapshot_timer.stop()
    quality_dashboard = getattr(app, "quality_dashboard_dialog", None)
    if quality_dashboard is not None:
        quality_dashboard.close()
        app.quality_dashboard_dialog = None
    app._last_auto_snapshot_marker = None
    app.database_session.close(app.conn)
    app.conn = None
    app.cursor = None
    app.track_service = None
    app._audio_waveform_cache_service_instance = None
    app.schema_service = None
    app.history_manager = None
    app.profile_kv = None
    app.history_cleanup_service = None
    app.settings_reads = None
    app.settings_mutations = None
    app.blob_icon_settings_service = None
    app.settings_transfer_service = None
    app.code_registry_service = None
    app.contract_template_catalog_service = None
    app.contract_template_service = None
    app.contract_template_form_service = None
    app.contract_template_export_service = None
    app.gs1_settings_service = None
    app.gs1_integration_service = None
    app.catalog_service = None
    app.catalog_reads = None
    app.promo_code_service = None
    app.license_service = None
    app.custom_field_definitions = None
    app.custom_field_values = None
    app.xml_export_service = None
    app.xml_import_service = None
    app.release_service = None
    app.authenticity_key_service = None
    app.authenticity_manifest_service = None
    app.audio_watermark_service = None
    app.audio_authenticity_service = None
    app.forensic_watermark_service = None
    app.forensic_export_service = None
    app.party_service = None
    app.work_service = None
    app.contract_service = None
    app.license_migration_service = None
    app.rights_service = None
    app.asset_service = None
    app.repertoire_workflow_service = None
    app.global_search_service = None
    app.relationship_explorer_service = None
    app.audio_tag_service = None
    app.tagged_audio_export_service = None
    app.exchange_service = None
    app.conversion_service = ConversionService()
    app.conversion_template_store_service = None
    app.party_exchange_service = None
    app.repertoire_exchange_service = None
    app.quality_service = None
    app._pending_work_track_context = None
    if hasattr(app, "background_service_factory"):
        app.background_service_factory.db_path = None
    app._background_write_lock = None
    if closing_path:
        _forget_session_database_password(app, closing_path)


def _prepare_database_session(app, path: str, *, progress_callback=None) -> str:
    target_path = str(Path(path))
    if callable(progress_callback):
        progress_callback(1, 4, "Opening profile database session...")
    session = app.database_session.open(target_path)
    prepared_path = target_path
    try:
        schema_service = DatabaseSchemaService(
            session.conn,
            logger=app.logger,
            audit_callback=app._background_schema_audit_callback(session.conn),
            audit_commit=session.conn.commit,
            data_root=app.data_root,
        )
        if callable(progress_callback):
            progress_callback(2, 4, "Initializing required database tables...")
        schema_service.init_db()
        if callable(progress_callback):
            progress_callback(3, 4, "Applying schema migrations and checks...")
        schema_service.migrate_schema()
    finally:
        app.database_session.close(session.conn)
    if callable(progress_callback):
        progress_callback(4, 4, "Profile database prepared.")
    return prepared_path


def _prepare_database_for_open_blocking(
    app,
    path: str,
    *,
    title: str,
    description: str,
) -> bool:
    target_path = str(Path(path))
    app._report_startup_phase(StartupPhase.PREPARING_DATABASE)
    try:
        prepared_path = app._prepare_database_session(
            target_path,
            progress_callback=app._startup_progress_callback(StartupPhase.PREPARING_DATABASE),
        )
    except Exception as exc:
        app.logger.warning(
            "Database preparation failed for %s: %s",
            target_path,
            exc,
        )
        app.logger.debug(
            "Database preparation traceback for %s",
            target_path,
            exc_info=True,
        )
        return False
    return str(prepared_path or "").strip() == target_path


def open_database(
    app,
    path: str,
    *,
    schema_prepared: bool = False,
    progress_callback=None,
):
    """Open (or create) the SQLite DB at path; initialize schema if needed."""
    total_steps = 6 if schema_prepared else 8
    completed_steps = 0

    def _advance(message: str) -> None:
        nonlocal completed_steps
        completed_steps += 1
        if callable(progress_callback):
            progress_callback(completed_steps, total_steps, message)

    target_session_password = _session_database_password(app, path)
    if app.conn is not None or app.cursor is not None:
        app._close_database_connection()
        if target_session_password:
            _set_session_database_password(app, path, target_session_password)
    session = app.database_session.open(path)
    app.conn = session.conn
    app.cursor = session.cursor
    app.current_db_path = path
    _advance("Opened profile database connection.")
    app._configure_background_runtime()
    _advance("Configured background runtime services.")
    app._report_startup_phase(StartupPhase.LOADING_SERVICES)
    app._init_services()
    _advance("Loaded profile service layer.")

    app._migrate_artist_code_from_qsettings_if_needed()
    _advance("Restored migrated profile settings.")

    current_code = app.load_artist_code()

    app._log_event(
        "profile.open",
        "Opened profile database",
        path=path,
        artist_code=current_code,
    )

    app.database_session.remember_last_path(app.settings, path)
    app.logger.info("Settings synced to disk")

    # Create base tables/indices if missing
    if not schema_prepared:
        app._report_startup_phase(StartupPhase.PREPARING_DATABASE)
        app.init_db()
        _advance("Ensured required database tables exist.")

        # Run schema migrations and then refresh caches that depend on schema
        try:
            app.migrate_schema()
            if app.code_registry_service is not None:
                app.code_registry_service.ensure_default_categories()
        except Exception as e:
            app.logger.exception(f"Schema migration failed: {e}")
            app._run_startup_message_box(
                title="Migration Error",
                icon=QMessageBox.Critical,
                text=f"Database migration failed:\n{e}",
            )
            # keep going; DB might still be usable
        if app.history_manager is not None:
            app.history_manager._ensure_history_invariants()
        _advance("Completed schema migrations and history checks.")

    app._migrate_legacy_owner_party_if_needed()
    app._sync_application_isrc_registry()
    app.blob_icon_settings = app._load_blob_icon_settings()
    app.active_custom_fields = app.load_active_custom_fields()
    app._refresh_catalog_workspace_docks()
    _advance("Loaded profile metadata and refreshed workspace shells.")

    # now it's safe to write AuditLog
    app._audit("PROFILE", "Database", ref_id=path, details="open_database()")
    app._audit_commit()
    app._refresh_history_actions()
    app._last_auto_snapshot_marker = app._current_auto_snapshot_marker()
    app._refresh_auto_snapshot_schedule()
    _advance("Profile database ready for catalog loading.")


def _activate_profile(app, path: str, *, save_current_header: bool = True):
    if save_current_header:
        try:
            app._save_header_state(record_history=False)
        except Exception:
            pass

    app.open_database(path)
    app._reset_catalog_zoom_for_profile_change()

    with app._suspend_table_layout_history():
        try:
            app.active_custom_fields = app.load_active_custom_fields()
            app._rebuild_table_headers()
            app._load_header_state()
        except Exception:
            pass

        app._reload_profiles_list(select_path=path)
        app.refresh_table_preserve_view()
        app.populate_all_comboboxes()
        app._update_add_data_generated_fields()
        app._refresh_history_actions()
        app._schedule_owner_party_bootstrap()


def _prepare_profile_database_background(
    app,
    path: str,
    *,
    title: str,
    description: str,
    show_dialog: bool = True,
    on_success,
    on_error=None,
    on_finished=None,
    progress_callback=None,
) -> str | None:
    target_path = str(Path(path))

    def _worker(ctx):
        ctx.set_status(description)
        return app._prepare_database_session(
            target_path,
            progress_callback=lambda value, maximum, message: ctx.report_progress(
                value=value,
                maximum=maximum,
                message=message,
            ),
        )

    def _handle_error(failure: TaskFailure) -> None:
        if on_error is not None:
            on_error(failure)
            return
        app._show_background_task_error(
            title,
            failure,
            user_message="Could not prepare the selected profile:",
        )

    return app._submit_background_task(
        title=title,
        description=description,
        task_fn=_worker,
        kind="exclusive",
        unique_key=f"profile.prepare.{target_path}",
        requires_profile=False,
        show_dialog=show_dialog,
        cancellable=False,
        owner=app,
        on_success=on_success,
        on_finished=on_finished,
        on_error=_handle_error,
        on_progress=(
            (lambda update: progress_callback(update.value, update.maximum, update.message))
            if callable(progress_callback)
            else None
        ),
    )


def _activate_profile_in_background(
    app,
    path: str,
    *,
    save_current_header: bool = True,
    title: str = "Open Profile",
    description: str = "Preparing the selected profile database...",
    on_activated=None,
) -> str | None:
    if save_current_header:
        try:
            app._save_header_state(record_history=False)
        except Exception:
            pass

    loading_feedback = app._create_runtime_loading_feedback()
    loading_progress_tracker = (
        StartupProgressTracker.for_profile_loading(loading_feedback)
        if loading_feedback is not None
        else None
    )
    if loading_feedback is not None:
        if loading_progress_tracker is not None:
            loading_progress_tracker.set_phase(StartupPhase.OPENING_PROFILE_DB, description)
            loading_progress_tracker.complete_phase(
                StartupPhase.OPENING_PROFILE_DB,
                "Selected profile database for activation.",
            )
        else:
            app._set_loading_feedback_phase(
                loading_feedback,
                StartupPhase.OPENING_PROFILE_DB,
                description,
            )

    prepared = {"path": None}

    def _success(prepared_path: str):
        prepared["path"] = str(prepared_path)

    def _error(failure: TaskFailure) -> None:
        try:
            app._show_background_task_error(
                title,
                failure,
                user_message="Could not prepare the selected profile:",
            )
        finally:
            app._finish_loading_feedback(loading_feedback)

    def _report_activation_failure(prepared_path: str, exc: BaseException) -> None:
        traceback_text = traceback.format_exc()
        try:
            app.logger.exception("Profile activation failed for %s: %s", prepared_path, exc)
        except Exception:
            pass
        try:
            app._show_background_task_error(
                title,
                TaskFailure(message=str(exc), traceback_text=traceback_text),
                user_message="Could not activate the selected profile:",
            )
        except Exception:
            pass

    loading_feedback_finished = False

    def _finish_profile_loading_feedback() -> None:
        nonlocal loading_feedback_finished
        if loading_feedback_finished:
            return
        loading_feedback_finished = True
        try:
            if loading_progress_tracker is not None:
                loading_progress_tracker.finish()
        finally:
            app._finish_loading_feedback(loading_feedback)

    def _finished():
        prepared_path = str(prepared.get("path") or "").strip()
        if not prepared_path:
            app._finish_loading_feedback(loading_feedback)
            return
        try:
            if loading_progress_tracker is not None:
                loading_progress_tracker.set_phase(
                    StartupPhase.LOADING_SERVICES,
                    "Opening selected profile database...",
                )
            else:
                app._set_loading_feedback_phase(
                    loading_feedback,
                    StartupPhase.LOADING_SERVICES,
                    "Opening selected profile database...",
                )
            if loading_feedback is not None:
                app._drain_qt_events()
            app.open_database(
                prepared_path,
                schema_prepared=True,
                progress_callback=app._loading_feedback_progress_callback(
                    loading_feedback,
                    loading_progress_tracker,
                    StartupPhase.LOADING_SERVICES,
                ),
            )
            app._reset_catalog_zoom_for_profile_change()
            with app._suspend_table_layout_history():
                interface_progress = app._loading_feedback_progress_callback(
                    loading_feedback,
                    loading_progress_tracker,
                    StartupPhase.FINALIZING_INTERFACE,
                )
                try:
                    app.active_custom_fields = app.load_active_custom_fields()
                    interface_progress(
                        1, 3, "Loaded active custom fields for the selected profile."
                    )
                    app._rebuild_table_headers()
                    interface_progress(2, 3, "Rebuilt catalog headers for the selected profile.")
                    app._load_header_state()
                except Exception:
                    pass
                interface_progress(3, 3, "Restored header state and profile selection.")
                app._reload_profiles_list(select_path=prepared_path)
                if loading_progress_tracker is not None:
                    loading_progress_tracker.set_phase(
                        StartupPhase.LOADING_CATALOG,
                        "Loading catalog rows and workspace data...",
                    )
                else:
                    app._set_loading_feedback_phase(
                        loading_feedback,
                        StartupPhase.LOADING_CATALOG,
                        "Loading catalog rows and workspace data...",
                    )
                if loading_feedback is not None:
                    app._drain_qt_events()

                def _profile_catalog_loaded() -> None:
                    try:
                        if on_activated is not None:
                            on_activated(prepared_path)
                        app._schedule_owner_party_bootstrap()
                    except Exception as exc:
                        _report_activation_failure(prepared_path, exc)

                task_id = app._refresh_catalog_ui_in_background(
                    select_path=prepared_path,
                    unique_key=f"catalog.ui.profile.{prepared_path}",
                    show_dialog=loading_feedback is None,
                    on_finished=_profile_catalog_loaded,
                    on_complete=_finish_profile_loading_feedback,
                    progress_callback=app._loading_feedback_progress_callback(
                        loading_feedback,
                        loading_progress_tracker,
                        StartupPhase.LOADING_CATALOG,
                    ),
                )
                if task_id is None:
                    _finish_profile_loading_feedback()
        except Exception as exc:
            _finish_profile_loading_feedback()
            _report_activation_failure(prepared_path, exc)

    task_id = app._prepare_profile_database_background(
        path,
        title=title,
        description=description,
        show_dialog=loading_feedback is None,
        on_success=_success,
        on_error=_error,
        on_finished=_finished,
        progress_callback=app._loading_feedback_progress_callback(
            loading_feedback,
            loading_progress_tracker,
            StartupPhase.PREPARING_DATABASE,
        ),
    )
    return task_id


__all__ = [
    "_apply_storage_layout",
    "_reconcile_startup_storage_root",
    "_maybe_run_storage_layout_migration",
    "_run_storage_layout_migration",
    "_reload_profiles_list",
    "_on_profile_changed",
    "create_new_profile",
    "browse_profile",
    "change_current_database_password",
    "remove_selected_profile",
    "_close_database_connection",
    "_prepare_database_session",
    "_prepare_database_for_open_blocking",
    "open_database",
    "_activate_profile",
    "_prepare_profile_database_background",
    "_activate_profile_in_background",
]
