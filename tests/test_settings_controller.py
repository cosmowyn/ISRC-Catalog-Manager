from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest

import isrc_manager.settings_controller as settings_controller
from isrc_manager.app_sounds import (
    APP_SOUND_NOTICE,
    APP_SOUND_STARTUP,
    APP_SOUND_WARNING,
)
from isrc_manager.constants import DEFAULT_ICON_PATH, DEFAULT_WINDOW_TITLE
from isrc_manager.services import GS1ProfileDefaults, OwnerPartySettings
from isrc_manager.services.settings_reads import RegistrationSettings


class _Settings:
    def __init__(self, values: dict[str, object] | None = None):
        self.values = dict(values or {})
        self.stored: dict[str, object] = {}
        self.synced = False

    def contains(self, key: str) -> bool:
        return key in self.values

    def value(self, key: str, default=None, type_=None):
        return self.values.get(key, default)

    def setValue(self, key: str, value: object) -> None:
        self.stored[key] = value

    def sync(self) -> None:
        self.synced = True


class _StatusBar:
    def __init__(self):
        self.messages: list[tuple[str, int]] = []

    def showMessage(self, message: str, timeout: int) -> None:
        self.messages.append((message, timeout))


def _history_retention(**overrides):
    values = {
        "retention_mode": "balanced",
        "auto_cleanup_enabled": True,
        "storage_budget_mb": 512,
        "auto_snapshot_keep_latest": 5,
        "prune_pre_restore_copies_after_days": 30,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _base_values() -> dict[str, object]:
    return {
        "window_title": "",
        "effective_window_title": DEFAULT_WINDOW_TITLE,
        "icon_path": "",
        "theme_settings": {"selected_name": "", "font_family": "Default", "font_size": 11},
        "theme_library": {},
        "blob_icon_settings": {},
        "startup_sound_enabled": True,
        "notice_sound_enabled": True,
        "warning_sound_enabled": True,
        "app_sound_settings": {
            APP_SOUND_STARTUP: True,
            APP_SOUND_NOTICE: True,
            APP_SOUND_WARNING: True,
        },
        "remember_database_password": False,
        "suppress_unencrypted_profile_warnings": False,
        "artist_code": "ABC",
        "auto_snapshot_enabled": True,
        "auto_snapshot_interval_minutes": 15,
        "history_retention_mode": "balanced",
        "history_auto_cleanup_enabled": True,
        "history_storage_budget_mb": 512,
        "history_auto_snapshot_keep_latest": 5,
        "history_prune_pre_restore_copies_after_days": 30,
        "isrc_prefix": "NL-ABC",
        "sena_number": "SENA-1",
        "btw_number": "BTW-1",
        "buma_relatie_nummer": "REL-1",
        "buma_ipi": "IPI-1",
        "owner_party_id": 1,
        "owner_party_settings": OwnerPartySettings(company_name="Owner Co"),
        "owner_company_name": "Owner Co",
        "gs1_template_asset": None,
        "gs1_contracts_csv_path": "",
        "gs1_contract_entries": (),
        "gs1_active_contract_number": "C-1",
        "gs1_target_market": "NL",
        "gs1_language": "nl",
        "gs1_brand": "Brand",
        "gs1_subbrand": "",
        "gs1_packaging_type": "digital",
        "gs1_product_classification": "music",
    }


def _fake_app() -> SimpleNamespace:
    settings = _Settings()
    history_manager = mock.Mock()
    table = SimpleNamespace(viewport=lambda: SimpleNamespace(update=mock.Mock()))
    app = SimpleNamespace(
        DEFAULT_STARTUP_SOUND_ENABLED=True,
        settings=settings,
        settings_reads=mock.Mock(),
        settings_mutations=mock.Mock(),
        logger=mock.Mock(),
        history_manager=history_manager,
        identity={
            "window_title": DEFAULT_WINDOW_TITLE,
            "window_title_override": "",
            "icon_path": "",
        },
        theme_settings={"selected_name": "", "font_family": "Default", "font_size": 11},
        blob_icon_settings={},
        gs1_settings_service=None,
        gs1_integration_service=None,
        conn=mock.Mock(),
        table=table,
        party_service=mock.Mock(),
        current_db_path="/tmp/catalog.db",
    )
    app._stored_window_title_override = lambda: settings_controller._stored_window_title_override(
        app
    )
    app._current_owner_party_record = mock.Mock(return_value=None)
    app._current_owner_company_name = lambda: settings_controller._current_owner_company_name(app)
    app._resolve_window_title = lambda override=None: settings_controller._resolve_window_title(
        app, override
    )
    app._load_identity = lambda: settings_controller._load_identity(app)
    app._apply_identity = mock.Mock()
    app._current_auto_snapshot_settings = mock.Mock(return_value=(True, 15))
    app._current_history_retention_settings = mock.Mock(return_value=_history_retention())
    app._current_app_sound_settings = mock.Mock(
        return_value={
            APP_SOUND_STARTUP: True,
            APP_SOUND_NOTICE: True,
            APP_SOUND_WARNING: True,
        }
    )
    app._load_theme_settings = mock.Mock(return_value=app.theme_settings)
    app._load_theme_library = mock.Mock(return_value={})
    app._load_blob_icon_settings = mock.Mock(return_value={})
    app.load_artist_code = mock.Mock(return_value="ABC")
    app._current_settings_values = lambda: settings_controller._current_settings_values(app)
    app._apply_settings_changes = lambda before, after, **kwargs: (
        settings_controller._apply_settings_changes(app, before, after, **kwargs)
    )
    app._sanitize_theme_library = mock.Mock(side_effect=lambda value: dict(value or {}))
    app._save_theme_library = mock.Mock()
    app._normalize_theme_settings = mock.Mock(side_effect=lambda value: dict(value or {}))
    app._save_theme_settings = mock.Mock()
    app._apply_theme_with_loading = mock.Mock()
    app._apply_theme = mock.Mock()
    app._save_blob_icon_settings = mock.Mock()
    app._set_application_history_storage_budget_mb = mock.Mock(side_effect=lambda value: value)
    app._audit = mock.Mock()
    app._audit_commit = mock.Mock()
    app._log_event = mock.Mock()
    app._refresh_auto_snapshot_schedule = mock.Mock()
    app._enforce_history_storage_budget = mock.Mock()
    app._sync_application_isrc_registry = mock.Mock()
    app._update_add_data_generated_fields = mock.Mock()
    app._refresh_history_actions = mock.Mock()
    app._refresh_catalog_workspace_docks = mock.Mock()
    app._play_notice_sound = mock.Mock()
    app._play_warning_sound = mock.Mock()
    app._app_version_text = mock.Mock(return_value="3.14.5-test")
    app.statusBar = mock.Mock(return_value=_StatusBar())
    app.settings_mutations.set_owner_party_id.return_value = 2
    app.settings_reads.load_registration_settings.return_value = RegistrationSettings(
        isrc_prefix="NL-ABC",
        sena_number="SENA-1",
        btw_number="BTW-1",
        buma_relatie_nummer="REL-1",
        buma_ipi="IPI-1",
    )
    app.settings_reads.load_owner_party_settings.return_value = OwnerPartySettings(
        company_name="Owner Co"
    )
    app.settings_reads.load_owner_party_id.return_value = 1
    return app


def test_identity_helpers_resolve_override_legacy_owner_and_default(tmp_path: Path) -> None:
    app = _fake_app()
    app.settings = _Settings({"identity/window_title_override": "  Manual Title  "})
    assert settings_controller._stored_window_title_override(app) == "Manual Title"

    app.settings = _Settings({"identity/window_title": "Legacy Title"})
    assert settings_controller._stored_window_title_override(app) == "Legacy Title"

    app.settings = _Settings({"identity/window_title": DEFAULT_WINDOW_TITLE})
    app._current_owner_party_record = mock.Mock(
        return_value=SimpleNamespace(company_name="Owner Co")
    )
    assert settings_controller._current_owner_company_name(app) == "Owner Co"
    assert settings_controller._resolve_window_title(app, "") == "Owner Co"

    app._current_owner_party_record.return_value = None
    assert settings_controller._resolve_window_title(app, "") == DEFAULT_WINDOW_TITLE

    icon = tmp_path / "icon.png"
    icon.write_bytes(b"not-real-png")
    app.settings = _Settings({"identity/icon_path": str(icon)})
    app.identity = settings_controller._load_identity(app)
    app.setWindowTitle = mock.Mock()
    app.setWindowIcon = mock.Mock(side_effect=RuntimeError("bad icon"))

    settings_controller._apply_identity(app)

    app.setWindowTitle.assert_called_once_with(DEFAULT_WINDOW_TITLE)
    app.setWindowIcon.assert_called_once()
    assert settings_controller._load_identity(_fake_app())["icon_path"] == DEFAULT_ICON_PATH


def test_current_settings_values_collects_services_and_defaults() -> None:
    app = _fake_app()
    app.settings.values[settings_controller.DATABASE_REMEMBER_PASSWORD_SETTING] = "true"
    app.gs1_settings_service = mock.Mock()
    app.gs1_settings_service.load_profile_defaults.return_value = GS1ProfileDefaults(
        contract_number="C-1",
        target_market="NL",
        language="nl",
        brand="Brand",
        subbrand="Sub",
        packaging_type="digital",
        product_classification="music",
    )
    app.gs1_settings_service.load_contracts.return_value = ("contract",)
    app.gs1_settings_service.load_template_asset.return_value = "template"
    app.gs1_settings_service.load_contracts_csv_path.return_value = "/tmp/contracts.csv"

    values = settings_controller._current_settings_values(app)

    assert values["artist_code"] == "ABC"
    assert values["history_storage_budget_mb"] == 512
    assert values["owner_company_name"] == "Owner Co"
    assert values["gs1_template_asset"] == "template"
    assert values["gs1_contract_entries"] == ("contract",)
    assert values["gs1_subbrand"] == "Sub"
    assert values["remember_database_password"] is True
    assert values["suppress_unencrypted_profile_warnings"] is False


def test_apply_settings_changes_returns_zero_for_noop() -> None:
    app = _fake_app()
    values = _base_values()

    assert settings_controller._apply_settings_changes(app, values, dict(values)) == 0

    app._refresh_auto_snapshot_schedule.assert_not_called()
    app.settings_mutations.set_artist_code.assert_not_called()


def test_apply_settings_changes_disabling_database_password_remember_clears_keyring() -> None:
    app = _fake_app()
    app.database_keyring_credentials = mock.Mock()
    before = dict(_base_values(), remember_database_password=True)
    after = dict(before, remember_database_password=False)

    changed = settings_controller._apply_settings_changes(app, before, after)

    assert changed == 1
    assert app.settings.stored == {
        settings_controller.DATABASE_REMEMBER_PASSWORD_SETTING: False,
    }
    app.database_keyring_credentials.clear.assert_called_once_with("/tmp/catalog.db")


def test_apply_settings_changes_updates_unencrypted_profile_warning_global_setting() -> None:
    app = _fake_app()
    before = dict(_base_values(), suppress_unencrypted_profile_warnings=False)
    after = dict(before, suppress_unencrypted_profile_warnings=True)

    changed = settings_controller._apply_settings_changes(app, before, after)

    assert changed == 1
    assert app.settings.stored == {
        settings_controller.SUPPRESS_UNENCRYPTED_PROFILE_WARNING_SETTING: True,
    }
    app.history_manager.record_setting_change.assert_called_once()
    assert (
        app.history_manager.record_setting_change.call_args.kwargs["key"]
        == "suppress_unencrypted_profile_warnings"
    )


def test_apply_settings_changes_persists_changed_sections_and_confirmation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = _fake_app()
    app._apply_theme_with_loading.side_effect = RuntimeError("theme worker unavailable")
    app.gs1_settings_service = mock.Mock()
    app.gs1_settings_service.import_template_from_bytes.return_value = SimpleNamespace(
        filename="template.xlsx",
        storage_mode="database",
    )
    app.settings_mutations.set_history_storage_budget_mb = mock.Mock()
    before = _base_values()
    after = dict(before)
    after.update(
        {
            "window_title": "New Title",
            "icon_path": "/tmp/new-icon.png",
            "theme_library": {"Bright": {"font_family": "A"}},
            "theme_settings": {"selected_name": "Missing", "font_family": "A", "font_size": 12},
            "blob_icon_settings": {"audio_managed": {"mode": "emoji", "emoji": "X"}},
            "app_sound_settings": {
                APP_SOUND_STARTUP: False,
                APP_SOUND_NOTICE: True,
                APP_SOUND_WARNING: False,
            },
            "artist_code": "XYZ",
            "auto_snapshot_enabled": False,
            "auto_snapshot_interval_minutes": 30,
            "history_retention_mode": "minimal",
            "history_auto_cleanup_enabled": False,
            "history_storage_budget_mb": 1024,
            "history_auto_snapshot_keep_latest": 2,
            "history_prune_pre_restore_copies_after_days": 10,
            "isrc_prefix": "NL-XYZ",
            "sena_number": "SENA-2",
            "owner_party_id": 2,
            "gs1_template_import_bytes": b"xlsx",
            "gs1_template_import_filename": "template.xlsx",
            "gs1_contract_entries": ("contract-a",),
            "gs1_contracts_csv_path": "/tmp/contracts.csv",
            "gs1_active_contract_number": "C-2",
            "gs1_target_market": "BE",
            "gs1_language": "fr",
            "gs1_brand": "New Brand",
            "gs1_subbrand": "Sub",
            "gs1_packaging_type": "box",
            "gs1_product_classification": "release",
        }
    )
    monkeypatch.setattr(settings_controller.QMessageBox, "information", mock.Mock())

    changed = settings_controller._apply_settings_changes(
        app,
        before,
        after,
        show_confirmation=True,
    )

    assert changed >= 18
    app.settings_mutations.set_identity.assert_called_once_with(
        window_title_override="New Title",
        icon_path="/tmp/new-icon.png",
    )
    app._save_theme_library.assert_called_once()
    app._apply_theme.assert_called_once()
    app._save_blob_icon_settings.assert_called_once()
    app.settings_mutations.set_artist_code.assert_called_once_with("XYZ")
    app.settings_mutations.set_isrc_prefix.assert_called_once_with("NL-XYZ")
    app.settings_mutations.set_sena_number.assert_called_once_with("SENA-2")
    app.settings_mutations.set_owner_party_id.assert_called_once_with(2)
    app.gs1_settings_service.import_template_from_bytes.assert_called_once()
    app.gs1_settings_service.set_contracts.assert_called_once()
    app.gs1_settings_service.set_profile_defaults.assert_called_once()
    app._enforce_history_storage_budget.assert_called_once_with(
        trigger_label="settings update",
        interactive=True,
    )
    app._play_notice_sound.assert_called_once()
    settings_controller.QMessageBox.information.assert_called_once()


def test_settings_bool_coercion_and_soundcloud_focus_opener(monkeypatch: pytest.MonkeyPatch):
    assert settings_controller._coerce_bool(True) is True
    assert settings_controller._coerce_bool(None, default=True) is True
    assert settings_controller._coerce_bool("off", default=True) is False

    opener = mock.Mock()
    monkeypatch.setattr(settings_controller, "open_settings_dialog", opener)
    app = _fake_app()

    settings_controller.open_soundcloud_settings_dialog(app)

    opener.assert_called_once_with(app, initial_focus=settings_controller.SOUNDCLOUD_SETTINGS_FOCUS)


def test_apply_settings_changes_handles_gs1_template_path_clear_and_convert(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = _fake_app()
    app.gs1_settings_service = mock.Mock()
    app.gs1_integration_service = mock.Mock()
    app.gs1_integration_service.import_template_workbook.return_value = SimpleNamespace(
        source_path="/tmp/template.xlsx",
        filename="template.xlsx",
        storage_mode="managed_file",
    )
    before = _base_values()
    after = dict(
        before,
        gs1_template_import_path="/tmp/template.xlsx",
        gs1_template_storage_mode="managed_file",
    )

    changed = settings_controller._apply_settings_changes(app, before, after)

    assert changed == 1
    app.gs1_integration_service.import_template_workbook.assert_called_once_with(
        "/tmp/template.xlsx",
        storage_mode="managed_file",
    )

    app = _fake_app()
    app.gs1_settings_service = mock.Mock()
    before = dict(_base_values(), gs1_template_asset=SimpleNamespace(storage_mode="database"))
    after = dict(before, gs1_template_clear_existing=True)

    changed = settings_controller._apply_settings_changes(app, before, after)

    assert changed == 1
    app.gs1_settings_service.clear_stored_template.assert_called_once()

    app = _fake_app()
    app.gs1_settings_service = mock.Mock()
    app.gs1_settings_service.convert_template_storage_mode.return_value = SimpleNamespace(
        filename="template.xlsx",
        storage_mode="managed_file",
    )
    before = dict(_base_values(), gs1_template_asset=SimpleNamespace(storage_mode="database"))
    after = dict(before, gs1_template_storage_mode="managed_file")

    changed = settings_controller._apply_settings_changes(app, before, after)

    assert changed == 1
    app.gs1_settings_service.convert_template_storage_mode.assert_called_once_with("managed_file")

    app = _fake_app()
    app.gs1_settings_service = mock.Mock()
    before = dict(_base_values(), gs1_contract_entries=("contract-a",))
    after = dict(before, gs1_contract_entries=())

    changed = settings_controller._apply_settings_changes(app, before, after)

    assert changed == 1
    app.gs1_settings_service.clear_contracts.assert_called_once()

    app = _fake_app()
    app.gs1_settings_service = mock.Mock()
    app.conn = mock.Mock()
    app.gs1_settings_service.import_template_from_path.side_effect = RuntimeError("bad template")
    before = _base_values()
    after = dict(before, gs1_template_import_path="/tmp/bad-template.xlsx")

    with pytest.raises(RuntimeError, match="bad template"):
        settings_controller._apply_settings_changes(app, before, after)

    app.conn.rollback.assert_called_once()


def test_export_and_import_settings_bundle_dialog_paths(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    app = _fake_app()
    app.settings_transfer_service = mock.Mock()
    app.settings_transfer_service.export_bundle.return_value = tmp_path / "settings.zip"
    app.settings_transfer_service.prepare_import.return_value = SimpleNamespace(
        values=dict(_base_values(), artist_code="IMP"),
        warnings=["minor issue"],
    )
    app.current_db_path = str(tmp_path / "profile.sqlite")
    monkeypatch.setattr(
        settings_controller.QFileDialog,
        "getSaveFileName",
        mock.Mock(return_value=(str(tmp_path / "settings.zip"), "ZIP")),
    )
    monkeypatch.setattr(
        settings_controller.QFileDialog,
        "getOpenFileName",
        mock.Mock(return_value=(str(tmp_path / "settings.zip"), "ZIP")),
    )
    monkeypatch.setattr(settings_controller.QMessageBox, "information", mock.Mock())
    monkeypatch.setattr(settings_controller.QMessageBox, "warning", mock.Mock())
    monkeypatch.setattr(
        settings_controller.QMessageBox,
        "question",
        mock.Mock(return_value=settings_controller.QMessageBox.Yes),
    )
    before_values = _base_values()
    app._current_settings_values = mock.Mock(return_value=before_values)
    app._apply_settings_changes = mock.Mock(return_value=1)

    settings_controller.export_application_settings_bundle(app)
    settings_controller.import_application_settings_bundle(app)

    app.settings_transfer_service.export_bundle.assert_called_once()
    app.settings_transfer_service.prepare_import.assert_called_once_with(
        str(tmp_path / "settings.zip"),
        current_values=before_values,
    )
    app._apply_settings_changes.assert_called_once()
    assert settings_controller.QMessageBox.information.call_count == 2


def test_open_settings_dialog_accepts_cancels_and_reports_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = _fake_app()
    app.party_service = "party-service"
    before_values = _base_values()
    app._current_settings_values = mock.Mock(return_value=before_values)
    accepted_dialogs: list[object] = []

    class _AcceptedDialog:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self.focus_field = mock.Mock()
            accepted_dialogs.append(self)

        def exec(self) -> int:
            return settings_controller.QDialog.Accepted

        def values(self) -> dict[str, object]:
            return dict(before_values, artist_code="XYZ")

    monkeypatch.setattr(settings_controller, "ApplicationSettingsDialog", _AcceptedDialog)
    app._apply_settings_changes = mock.Mock(return_value=1)

    settings_controller.open_settings_dialog(app, initial_focus="artist_code")

    assert accepted_dialogs[0].kwargs["party_service"] == "party-service"
    assert accepted_dialogs[0].kwargs["suppress_unencrypted_profile_warnings"] is False
    accepted_dialogs[0].focus_field.assert_called_once_with("artist_code")
    app._apply_settings_changes.assert_called_once()

    class _RejectedDialog(_AcceptedDialog):
        def exec(self) -> int:
            return settings_controller.QDialog.Rejected

    monkeypatch.setattr(settings_controller, "ApplicationSettingsDialog", _RejectedDialog)
    app._apply_settings_changes.reset_mock()

    settings_controller.open_settings_dialog(app)

    app._apply_settings_changes.assert_not_called()

    monkeypatch.setattr(settings_controller, "ApplicationSettingsDialog", _AcceptedDialog)
    app._apply_settings_changes = mock.Mock(side_effect=RuntimeError("save failed"))
    monkeypatch.setattr(settings_controller.QMessageBox, "critical", mock.Mock())

    settings_controller.open_settings_dialog(app)

    app._play_warning_sound.assert_called_once()
    settings_controller.QMessageBox.critical.assert_called_once()


def test_export_settings_bundle_handles_cancel_and_export_errors(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    app = _fake_app()
    app.settings_transfer_service = mock.Mock()
    app.current_db_path = str(tmp_path / "profile.sqlite")
    monkeypatch.setattr(
        settings_controller.QFileDialog,
        "getSaveFileName",
        mock.Mock(return_value=("", "")),
    )

    settings_controller.export_application_settings_bundle(app)

    app.settings_transfer_service.export_bundle.assert_not_called()

    monkeypatch.setattr(
        settings_controller.QFileDialog,
        "getSaveFileName",
        mock.Mock(return_value=(str(tmp_path / "settings.zip"), "ZIP")),
    )
    app.settings_transfer_service.export_bundle.side_effect = RuntimeError("write failed")
    monkeypatch.setattr(settings_controller.QMessageBox, "warning", mock.Mock())

    settings_controller.export_application_settings_bundle(app)

    app._play_warning_sound.assert_called_once()
    settings_controller.QMessageBox.warning.assert_called_once()


def test_import_settings_bundle_handles_cancel_decline_errors_and_noop_message(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    app = _fake_app()
    app.settings_transfer_service = mock.Mock()
    app.settings_transfer_service.prepare_import.return_value = SimpleNamespace(
        values=_base_values(),
        warnings=[],
    )
    monkeypatch.setattr(
        settings_controller.QFileDialog,
        "getOpenFileName",
        mock.Mock(return_value=("", "")),
    )

    settings_controller.import_application_settings_bundle(app)

    app.settings_transfer_service.prepare_import.assert_not_called()

    monkeypatch.setattr(
        settings_controller.QFileDialog,
        "getOpenFileName",
        mock.Mock(return_value=(str(tmp_path / "settings.zip"), "ZIP")),
    )
    monkeypatch.setattr(
        settings_controller.QMessageBox,
        "question",
        mock.Mock(return_value=settings_controller.QMessageBox.No),
    )

    settings_controller.import_application_settings_bundle(app)

    app.settings_transfer_service.prepare_import.assert_not_called()

    monkeypatch.setattr(
        settings_controller.QMessageBox,
        "question",
        mock.Mock(return_value=settings_controller.QMessageBox.Yes),
    )
    monkeypatch.setattr(settings_controller.QMessageBox, "warning", mock.Mock())
    app.settings_transfer_service.prepare_import.side_effect = RuntimeError("bad bundle")

    settings_controller.import_application_settings_bundle(app)

    app._play_warning_sound.assert_called_once()
    settings_controller.QMessageBox.warning.assert_called_once()

    app._play_warning_sound.reset_mock()
    app.settings_transfer_service.prepare_import.side_effect = None
    app.settings_transfer_service.prepare_import.return_value = SimpleNamespace(
        values=_base_values(),
        warnings=[],
    )
    app._apply_settings_changes = mock.Mock(return_value=0)
    monkeypatch.setattr(settings_controller.QMessageBox, "information", mock.Mock())

    settings_controller.import_application_settings_bundle(app)

    settings_controller.QMessageBox.information.assert_called_once()
    assert "No persisted settings needed to change" in (
        settings_controller.QMessageBox.information.call_args.args[2]
    )


def test_settings_bundle_dialogs_warn_without_open_profile(monkeypatch: pytest.MonkeyPatch) -> None:
    app = _fake_app()
    app.conn = None
    app.settings_transfer_service = None
    monkeypatch.setattr(settings_controller.QMessageBox, "warning", mock.Mock())

    settings_controller.export_application_settings_bundle(app)
    settings_controller.import_application_settings_bundle(app)

    assert app._play_warning_sound.call_count == 2
    assert settings_controller.QMessageBox.warning.call_count == 2


def test_apply_single_setting_value_delegates_to_change_orchestrator() -> None:
    app = _fake_app()
    app._current_settings_values = mock.Mock(return_value=_base_values())
    app._apply_settings_changes = mock.Mock(return_value=1)

    assert settings_controller._apply_single_setting_value(app, "artist_code", "XYZ") == 1
    before, after = app._apply_settings_changes.call_args.args
    assert before["artist_code"] == "ABC"
    assert after["artist_code"] == "XYZ"
