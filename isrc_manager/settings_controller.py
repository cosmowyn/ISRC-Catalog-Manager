"""Application settings dialog and settings-bundle orchestration."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QDialog, QFileDialog, QMessageBox

from isrc_manager.app_sounds import (
    APP_SOUND_NOTICE,
    APP_SOUND_SETTINGS_KEYS,
    APP_SOUND_STARTUP,
    APP_SOUND_WARNING,
    normalize_app_sound_settings,
)
from isrc_manager.application_settings_dialog import ApplicationSettingsDialog
from isrc_manager.blob_icons import describe_blob_icon_spec, normalize_blob_icon_settings
from isrc_manager.constants import DEFAULT_ICON_PATH, DEFAULT_WINDOW_TITLE
from isrc_manager.file_storage import (
    STORAGE_MODE_DATABASE,
    normalize_storage_mode,
    sanitize_export_basename,
)
from isrc_manager.services import GS1ProfileDefaults, OwnerPartySettings
from isrc_manager.storage_sizes import format_budget_megabytes


def _stored_window_title_override(app) -> str:
    if app.settings.contains("identity/window_title_override"):
        return str(app.settings.value("identity/window_title_override", "", str) or "").strip()
    legacy_title = str(app.settings.value("identity/window_title", "", str) or "").strip()
    if legacy_title and legacy_title not in {DEFAULT_WINDOW_TITLE, "ISRC Manager"}:
        return legacy_title
    return ""


def _current_owner_company_name(app) -> str:
    record = app._current_owner_party_record()
    if record is None:
        return ""
    return str(record.company_name or "").strip()


def _resolve_window_title(app, override: str | None = None) -> str:
    manual_override = str(override or "").strip()
    if manual_override:
        return manual_override
    owner_company_name = app._current_owner_company_name()
    if owner_company_name:
        return owner_company_name
    return DEFAULT_WINDOW_TITLE


def _load_identity(app):
    window_title_override = app._stored_window_title_override()
    icon = app.settings.value("identity/icon_path", DEFAULT_ICON_PATH, str)
    return {
        "window_title": app._resolve_window_title(window_title_override),
        "window_title_override": window_title_override,
        "icon_path": icon,
    }


def _apply_identity(app):
    app.setWindowTitle(app.identity.get("window_title") or DEFAULT_WINDOW_TITLE)
    icon_path = app.identity.get("icon_path") or ""
    if icon_path and Path(icon_path).exists():
        try:
            app.setWindowIcon(QIcon(icon_path))
        except Exception:
            pass


def _current_settings_values(app) -> dict[str, object]:
    registration = app.settings_reads.load_registration_settings()
    auto_snapshot_enabled, auto_snapshot_interval_minutes = app._current_auto_snapshot_settings()
    history_retention = app._current_history_retention_settings()
    gs1_defaults = (
        app.gs1_settings_service.load_profile_defaults()
        if app.gs1_settings_service is not None
        else None
    )
    gs1_contracts = (
        app.gs1_settings_service.load_contracts() if app.gs1_settings_service is not None else ()
    )
    owner_party_settings = (
        app.settings_reads.load_owner_party_settings() if app.settings_reads is not None else None
    )
    app_sound_settings = app._current_app_sound_settings()
    return {
        "window_title": app.identity.get("window_title_override") or "",
        "effective_window_title": app.identity.get("window_title") or DEFAULT_WINDOW_TITLE,
        "icon_path": app.identity.get("icon_path") or "",
        "theme_settings": dict(app.theme_settings or app._load_theme_settings()),
        "theme_library": app._load_theme_library(),
        "blob_icon_settings": dict(app.blob_icon_settings or app._load_blob_icon_settings()),
        "startup_sound_enabled": app_sound_settings[APP_SOUND_STARTUP],
        "notice_sound_enabled": app_sound_settings[APP_SOUND_NOTICE],
        "warning_sound_enabled": app_sound_settings[APP_SOUND_WARNING],
        "app_sound_settings": app_sound_settings,
        "artist_code": app.load_artist_code(),
        "auto_snapshot_enabled": auto_snapshot_enabled,
        "auto_snapshot_interval_minutes": auto_snapshot_interval_minutes,
        "history_retention_mode": str(history_retention.retention_mode or ""),
        "history_auto_cleanup_enabled": bool(history_retention.auto_cleanup_enabled),
        "history_storage_budget_mb": int(history_retention.storage_budget_mb),
        "history_auto_snapshot_keep_latest": int(history_retention.auto_snapshot_keep_latest),
        "history_prune_pre_restore_copies_after_days": int(
            history_retention.prune_pre_restore_copies_after_days
        ),
        "isrc_prefix": registration.isrc_prefix,
        "sena_number": registration.sena_number,
        "btw_number": registration.btw_number,
        "buma_relatie_nummer": registration.buma_relatie_nummer,
        "buma_ipi": registration.buma_ipi,
        "owner_party_id": app.settings_reads.load_owner_party_id(),
        "owner_party_settings": owner_party_settings or OwnerPartySettings(),
        "owner_company_name": (
            str(getattr(owner_party_settings, "company_name", "") or "").strip()
        ),
        "gs1_template_asset": (
            app.gs1_settings_service.load_template_asset()
            if app.gs1_settings_service is not None
            else None
        ),
        "gs1_contracts_csv_path": (
            app.gs1_settings_service.load_contracts_csv_path()
            if app.gs1_settings_service is not None
            else ""
        ),
        "gs1_contract_entries": tuple(gs1_contracts),
        "gs1_active_contract_number": (
            gs1_defaults.contract_number if gs1_defaults is not None else ""
        ),
        "gs1_target_market": gs1_defaults.target_market if gs1_defaults is not None else "",
        "gs1_language": gs1_defaults.language if gs1_defaults is not None else "",
        "gs1_brand": gs1_defaults.brand if gs1_defaults is not None else "",
        "gs1_subbrand": gs1_defaults.subbrand if gs1_defaults is not None else "",
        "gs1_packaging_type": gs1_defaults.packaging_type if gs1_defaults is not None else "",
        "gs1_product_classification": (
            gs1_defaults.product_classification if gs1_defaults is not None else ""
        ),
    }


def _apply_settings_changes(
    app,
    before_values: dict[str, object],
    after_values: dict[str, object],
    *,
    show_confirmation: bool = False,
) -> int:
    changed_count = 0
    history_policy_changed = False

    try:
        before_identity_state = {
            "window_title_override": before_values["window_title"],
            "icon_path": before_values["icon_path"],
        }
        before_identity = {
            **before_identity_state,
            "window_title": before_values.get("effective_window_title") or DEFAULT_WINDOW_TITLE,
        }
        after_identity_state = {
            "window_title_override": after_values["window_title"],
            "icon_path": after_values["icon_path"],
        }
        if after_identity_state != before_identity_state:
            app.settings_mutations.set_identity(
                window_title_override=after_identity_state["window_title_override"],
                icon_path=after_identity_state["icon_path"],
            )
            app.identity = app._load_identity()
            app._apply_identity()
            app.logger.info("Branding & identity updated")
            app._audit(
                "SETTINGS",
                "Identity",
                ref_id="QSettings",
                details=f"title={app.identity['window_title']}",
            )
            app._audit_commit()
            if app.history_manager is not None:
                app.history_manager.record_setting_change(
                    key="identity",
                    label="Update Branding & Identity",
                    before_value=before_identity,
                    after_value=dict(app.identity),
                )
            changed_count += 1

        before_theme_library = app._sanitize_theme_library(before_values.get("theme_library"))
        after_theme_library = app._sanitize_theme_library(after_values.get("theme_library"))
        if after_theme_library != before_theme_library:
            app._save_theme_library(after_theme_library)
            app.logger.info("Theme library updated")
            app._log_event(
                "settings.theme_library",
                "Theme library updated",
                stored_themes=len(after_theme_library),
            )
            if app.history_manager is not None:
                app.history_manager.record_setting_change(
                    key="theme_library",
                    label="Update Saved Themes",
                    before_value=before_theme_library,
                    after_value=after_theme_library,
                )
            changed_count += 1

        before_theme = app._normalize_theme_settings(before_values.get("theme_settings"))
        after_theme = app._normalize_theme_settings(after_values.get("theme_settings"))
        if (
            after_theme.get("selected_name")
            and after_theme["selected_name"] not in after_theme_library
        ):
            after_theme["selected_name"] = ""
        if after_theme != before_theme:
            app._save_theme_settings(after_theme)
            try:
                app._apply_theme_with_loading(after_theme)
            except Exception as exc:
                app.logger.warning(
                    "Theme preparation task failed, falling back to direct apply: %s",
                    exc,
                )
                app._apply_theme(after_theme)
            app.logger.info("Theme settings updated")
            app._log_event(
                "settings.theme",
                "Theme settings updated",
                font_family=after_theme.get("font_family"),
                font_size=after_theme.get("font_size"),
            )
            if app.history_manager is not None:
                app.history_manager.record_setting_change(
                    key="theme_settings",
                    label="Update Theme Settings",
                    before_value=before_theme,
                    after_value=after_theme,
                )
            changed_count += 1

        before_blob_icons = normalize_blob_icon_settings(before_values.get("blob_icon_settings"))
        after_blob_icons = normalize_blob_icon_settings(after_values.get("blob_icon_settings"))
        if after_blob_icons != before_blob_icons:
            app._save_blob_icon_settings(after_blob_icons)
            app.logger.info("Blob icon settings updated")
            app._log_event(
                "settings.blob_icons",
                "Blob icon settings updated",
                audio_managed=describe_blob_icon_spec(
                    after_blob_icons.get("audio_managed"),
                    kind="audio_managed",
                ),
                audio_database=describe_blob_icon_spec(
                    after_blob_icons.get("audio_database"),
                    kind="audio_database",
                ),
                audio_lossy_managed=describe_blob_icon_spec(
                    after_blob_icons.get("audio_lossy_managed"),
                    kind="audio_lossy_managed",
                ),
                audio_lossy_database=describe_blob_icon_spec(
                    after_blob_icons.get("audio_lossy_database"),
                    kind="audio_lossy_database",
                ),
                image_managed=describe_blob_icon_spec(
                    after_blob_icons.get("image_managed"),
                    kind="image_managed",
                ),
                image_database=describe_blob_icon_spec(
                    after_blob_icons.get("image_database"),
                    kind="image_database",
                ),
            )
            if app.history_manager is not None:
                app.history_manager.record_setting_change(
                    key="blob_icon_settings",
                    label="Update Blob Icon Settings",
                    before_value=before_blob_icons,
                    after_value=after_blob_icons,
                )
            changed_count += 1
            if hasattr(app, "table"):
                app.table.viewport().update()

        before_app_sounds = normalize_app_sound_settings(
            before_values.get("app_sound_settings"),
            startup_sound_enabled=before_values.get(
                "startup_sound_enabled", app.DEFAULT_STARTUP_SOUND_ENABLED
            ),
        )
        after_app_sounds = normalize_app_sound_settings(
            after_values.get("app_sound_settings"),
            startup_sound_enabled=after_values.get(
                "startup_sound_enabled", app.DEFAULT_STARTUP_SOUND_ENABLED
            ),
        )
        if after_app_sounds != before_app_sounds:
            for sound_id, enabled in after_app_sounds.items():
                app.settings.setValue(APP_SOUND_SETTINGS_KEYS[sound_id], bool(enabled))
            app.settings.sync()
            app._log_event(
                "settings.app_sounds",
                "Application sound settings updated",
                **{
                    f"{sound_id}_enabled": enabled for sound_id, enabled in after_app_sounds.items()
                },
            )
            if app.history_manager is not None:
                app.history_manager.record_setting_change(
                    key="app_sound_settings",
                    label="Update Application Sounds",
                    before_value=before_app_sounds,
                    after_value=after_app_sounds,
                )
            changed_count += 1

        if after_values["artist_code"] != before_values["artist_code"]:
            app.settings_mutations.set_artist_code(after_values["artist_code"])
            app.logger.info(f"ISRC artist code set to '{after_values['artist_code']}' (profile DB)")
            if app.history_manager is not None:
                app.history_manager.record_setting_change(
                    key="artist_code",
                    label=f"Set ISRC Artist Code: {after_values['artist_code']}",
                    before_value=before_values["artist_code"],
                    after_value=after_values["artist_code"],
                )
            changed_count += 1

        if after_values["auto_snapshot_enabled"] != before_values["auto_snapshot_enabled"]:
            app.settings_mutations.set_auto_snapshot_enabled(
                bool(after_values["auto_snapshot_enabled"])
            )
            app._log_event(
                "settings.auto_snapshot_enabled",
                "Automatic snapshots setting updated",
                enabled=bool(after_values["auto_snapshot_enabled"]),
            )
            if app.history_manager is not None:
                app.history_manager.record_setting_change(
                    key="auto_snapshot_enabled",
                    label=(
                        "Automatic Snapshots Enabled"
                        if after_values["auto_snapshot_enabled"]
                        else "Automatic Snapshots Disabled"
                    ),
                    before_value=before_values["auto_snapshot_enabled"],
                    after_value=after_values["auto_snapshot_enabled"],
                )
            changed_count += 1

        if (
            after_values["auto_snapshot_interval_minutes"]
            != before_values["auto_snapshot_interval_minutes"]
        ):
            app.settings_mutations.set_auto_snapshot_interval_minutes(
                int(after_values["auto_snapshot_interval_minutes"])
            )
            app._log_event(
                "settings.auto_snapshot_interval_minutes",
                "Automatic snapshot interval updated",
                interval_minutes=int(after_values["auto_snapshot_interval_minutes"]),
            )
            if app.history_manager is not None:
                app.history_manager.record_setting_change(
                    key="auto_snapshot_interval_minutes",
                    label=f"Set Auto Snapshot Interval: {int(after_values['auto_snapshot_interval_minutes'])} minutes",
                    before_value=before_values["auto_snapshot_interval_minutes"],
                    after_value=after_values["auto_snapshot_interval_minutes"],
                )
            changed_count += 1

        if after_values["history_retention_mode"] != before_values["history_retention_mode"]:
            app.settings_mutations.set_history_retention_mode(
                str(after_values["history_retention_mode"])
            )
            app._log_event(
                "settings.history_retention_mode",
                "History retention mode updated",
                mode=str(after_values["history_retention_mode"]),
            )
            if app.history_manager is not None:
                app.history_manager.record_setting_change(
                    key="history_retention_mode",
                    label=(
                        "Set History Retention Level: "
                        f"{str(after_values['history_retention_mode']).replace('_', ' ').title()}"
                    ),
                    before_value=before_values["history_retention_mode"],
                    after_value=after_values["history_retention_mode"],
                )
            changed_count += 1
            history_policy_changed = True

        if (
            after_values["history_auto_cleanup_enabled"]
            != before_values["history_auto_cleanup_enabled"]
        ):
            app.settings_mutations.set_history_auto_cleanup_enabled(
                bool(after_values["history_auto_cleanup_enabled"])
            )
            app._log_event(
                "settings.history_auto_cleanup_enabled",
                "History automatic cleanup setting updated",
                enabled=bool(after_values["history_auto_cleanup_enabled"]),
            )
            if app.history_manager is not None:
                app.history_manager.record_setting_change(
                    key="history_auto_cleanup_enabled",
                    label=(
                        "History Automatic Cleanup Enabled"
                        if after_values["history_auto_cleanup_enabled"]
                        else "History Automatic Cleanup Disabled"
                    ),
                    before_value=before_values["history_auto_cleanup_enabled"],
                    after_value=after_values["history_auto_cleanup_enabled"],
                )
            changed_count += 1
            history_policy_changed = True

        if after_values["history_storage_budget_mb"] != before_values["history_storage_budget_mb"]:
            saved_budget_mb = app._set_application_history_storage_budget_mb(
                int(after_values["history_storage_budget_mb"])
            )
            # Mirror the app-wide budget into the open profile so older app builds still
            # read a safe value if this database is opened there.
            app.settings_mutations.set_history_storage_budget_mb(saved_budget_mb)
            app._log_event(
                "settings.history_storage_budget_mb",
                "History storage budget updated",
                budget_mb=saved_budget_mb,
            )
            if app.history_manager is not None:
                app.history_manager.record_setting_change(
                    key="history_storage_budget_mb",
                    label=(
                        f"Set History Storage Budget: "
                        f"{format_budget_megabytes(saved_budget_mb)}"
                    ),
                    before_value=before_values["history_storage_budget_mb"],
                    after_value=saved_budget_mb,
                )
            changed_count += 1
            history_policy_changed = True

        if (
            after_values["history_auto_snapshot_keep_latest"]
            != before_values["history_auto_snapshot_keep_latest"]
        ):
            app.settings_mutations.set_history_auto_snapshot_keep_latest(
                int(after_values["history_auto_snapshot_keep_latest"])
            )
            app._log_event(
                "settings.history_auto_snapshot_keep_latest",
                "History auto-snapshot retention updated",
                keep_latest=int(after_values["history_auto_snapshot_keep_latest"]),
            )
            if app.history_manager is not None:
                app.history_manager.record_setting_change(
                    key="history_auto_snapshot_keep_latest",
                    label=(
                        "Set Automatic Snapshot Retention: "
                        f"{int(after_values['history_auto_snapshot_keep_latest'])}"
                    ),
                    before_value=before_values["history_auto_snapshot_keep_latest"],
                    after_value=after_values["history_auto_snapshot_keep_latest"],
                )
            changed_count += 1
            history_policy_changed = True

        if (
            after_values["history_prune_pre_restore_copies_after_days"]
            != before_values["history_prune_pre_restore_copies_after_days"]
        ):
            app.settings_mutations.set_history_prune_pre_restore_copies_after_days(
                int(after_values["history_prune_pre_restore_copies_after_days"])
            )
            app._log_event(
                "settings.history_prune_pre_restore_copies_after_days",
                "History pre-restore backup pruning updated",
                days=int(after_values["history_prune_pre_restore_copies_after_days"]),
            )
            if app.history_manager is not None:
                app.history_manager.record_setting_change(
                    key="history_prune_pre_restore_copies_after_days",
                    label=(
                        "Set Pre-Restore Backup Prune Age: "
                        f"{int(after_values['history_prune_pre_restore_copies_after_days'])} days"
                    ),
                    before_value=before_values["history_prune_pre_restore_copies_after_days"],
                    after_value=after_values["history_prune_pre_restore_copies_after_days"],
                )
            changed_count += 1
            history_policy_changed = True

        if after_values["isrc_prefix"] != before_values["isrc_prefix"]:
            app.settings_mutations.set_isrc_prefix(after_values["isrc_prefix"])
            app.logger.info(f"ISRC prefix updated to '{after_values['isrc_prefix']}'")
            app._audit(
                "SETTINGS",
                "ISRC_Prefix",
                ref_id=1,
                details=f"prefix={after_values['isrc_prefix']}",
            )
            app._audit_commit()
            if app.history_manager is not None:
                app.history_manager.record_setting_change(
                    key="isrc_prefix",
                    label=f"Set ISRC Prefix: {after_values['isrc_prefix']}",
                    before_value=before_values["isrc_prefix"],
                    after_value=after_values["isrc_prefix"],
                )
            changed_count += 1

        if after_values["sena_number"] != before_values["sena_number"]:
            app.settings_mutations.set_sena_number(after_values["sena_number"])
            app.logger.info("SENA number updated")
            app._audit("SETTINGS", "SENA", ref_id=1, details="updated")
            app._audit_commit()
            if app.history_manager is not None:
                app.history_manager.record_setting_change(
                    key="sena_number",
                    label="Set SENA Number",
                    before_value=before_values["sena_number"],
                    after_value=after_values["sena_number"],
                )
            changed_count += 1

        before_owner_party_id = before_values.get("owner_party_id")
        after_owner_party_id = after_values.get("owner_party_id")
        if after_owner_party_id != before_owner_party_id:
            saved_owner_party_id = app.settings_mutations.set_owner_party_id(after_owner_party_id)
            app.logger.info("Current owner party updated")
            if app.history_manager is not None:
                app.history_manager.record_setting_change(
                    key="owner_party_id",
                    label="Set Current Owner Party",
                    before_value=before_owner_party_id,
                    after_value=saved_owner_party_id,
                )
            app._refresh_catalog_workspace_docks()
            changed_count += 1

        if app.gs1_settings_service is not None:
            pending_template_path = str(after_values.get("gs1_template_import_path") or "").strip()
            pending_template_bytes = after_values.get("gs1_template_import_bytes")
            pending_template_filename = str(
                after_values.get("gs1_template_import_filename") or ""
            ).strip()
            clear_template_storage = bool(after_values.get("gs1_template_clear_existing"))
            requested_template_storage_mode = normalize_storage_mode(
                after_values.get("gs1_template_storage_mode"),
                default=STORAGE_MODE_DATABASE,
            )
            before_template_asset = before_values.get("gs1_template_asset")
            before_template_storage_mode = normalize_storage_mode(
                getattr(before_template_asset, "storage_mode", None),
                default=STORAGE_MODE_DATABASE if before_template_asset is not None else None,
            )
            if pending_template_bytes:
                stored_template = app.gs1_settings_service.import_template_from_bytes(
                    bytes(pending_template_bytes),
                    filename=pending_template_filename or "gs1-template.xlsx",
                    storage_mode=requested_template_storage_mode,
                )
                app._log_event(
                    "settings.gs1_template_workbook",
                    "GS1 template workbook imported from settings bundle",
                    stored_filename=stored_template.filename,
                    storage_mode=stored_template.storage_mode,
                )
                changed_count += 1
            elif pending_template_path:
                if app.gs1_integration_service is not None:
                    stored_template = app.gs1_integration_service.import_template_workbook(
                        pending_template_path,
                        storage_mode=requested_template_storage_mode,
                    )
                else:
                    stored_template = app.gs1_settings_service.import_template_from_path(
                        pending_template_path,
                        storage_mode=requested_template_storage_mode,
                    )
                app._log_event(
                    "settings.gs1_template_workbook",
                    "GS1 template workbook stored",
                    template_path=stored_template.source_path,
                    stored_filename=stored_template.filename,
                    storage_mode=stored_template.storage_mode,
                )
                changed_count += 1
            elif clear_template_storage and before_template_asset is not None:
                app.gs1_settings_service.clear_stored_template()
                app._log_event(
                    "settings.gs1_template_workbook",
                    "GS1 template workbook cleared",
                )
                changed_count += 1
            elif (
                before_template_asset is not None
                and requested_template_storage_mode is not None
                and requested_template_storage_mode != before_template_storage_mode
            ):
                stored_template = app.gs1_settings_service.convert_template_storage_mode(
                    requested_template_storage_mode
                )
                app._log_event(
                    "settings.gs1_template_workbook",
                    "GS1 template workbook storage mode updated",
                    stored_filename=stored_template.filename,
                    storage_mode=stored_template.storage_mode,
                )
                changed_count += 1

            before_gs1_defaults = GS1ProfileDefaults(
                contract_number=str(before_values.get("gs1_active_contract_number") or "").strip(),
                target_market=str(before_values.get("gs1_target_market") or "").strip(),
                language=str(before_values.get("gs1_language") or "").strip(),
                brand=str(before_values.get("gs1_brand") or "").strip(),
                subbrand=str(before_values.get("gs1_subbrand") or "").strip(),
                packaging_type=str(before_values.get("gs1_packaging_type") or "").strip(),
                product_classification=str(
                    before_values.get("gs1_product_classification") or ""
                ).strip(),
            )
            after_gs1_defaults = GS1ProfileDefaults(
                contract_number=str(after_values.get("gs1_active_contract_number") or "").strip(),
                target_market=str(after_values.get("gs1_target_market") or "").strip(),
                language=str(after_values.get("gs1_language") or "").strip(),
                brand=str(after_values.get("gs1_brand") or "").strip(),
                subbrand=str(after_values.get("gs1_subbrand") or "").strip(),
                packaging_type=str(after_values.get("gs1_packaging_type") or "").strip(),
                product_classification=str(
                    after_values.get("gs1_product_classification") or ""
                ).strip(),
            )
            before_contracts = tuple(before_values.get("gs1_contract_entries") or ())
            after_contracts = tuple(after_values.get("gs1_contract_entries") or ())
            before_contracts_csv = str(before_values.get("gs1_contracts_csv_path") or "").strip()
            after_contracts_csv = str(after_values.get("gs1_contracts_csv_path") or "").strip()
            pending_contract_bytes = after_values.get("gs1_contracts_csv_bytes")
            pending_contract_filename = str(
                after_values.get("gs1_contracts_csv_filename") or ""
            ).strip()
            if (
                pending_contract_bytes is not None
                or bool(pending_contract_filename)
                or after_contracts != before_contracts
                or after_contracts_csv != before_contracts_csv
            ):
                if after_contracts:
                    app.gs1_settings_service.set_contracts(
                        after_contracts,
                        source_path=after_contracts_csv,
                        source_bytes=pending_contract_bytes,
                        source_filename=pending_contract_filename,
                    )
                else:
                    app.gs1_settings_service.clear_contracts()
                app._log_event(
                    "settings.gs1_contracts",
                    "GS1 contract list updated",
                    contract_count=len(after_contracts),
                    csv_path=after_contracts_csv,
                )
                changed_count += 1
            if after_gs1_defaults != before_gs1_defaults:
                app.gs1_settings_service.set_profile_defaults(after_gs1_defaults)
                app._log_event(
                    "settings.gs1_defaults",
                    "GS1 profile defaults updated",
                    contract_number=after_gs1_defaults.contract_number,
                    target_market=after_gs1_defaults.target_market,
                    language=after_gs1_defaults.language,
                    brand=after_gs1_defaults.brand,
                    subbrand=after_gs1_defaults.subbrand,
                    packaging_type=after_gs1_defaults.packaging_type,
                    product_classification=after_gs1_defaults.product_classification,
                )
                changed_count += 1
    except Exception:
        if app.conn is not None:
            app.conn.rollback()
        raise

    if changed_count:
        app._refresh_auto_snapshot_schedule()
        if history_policy_changed:
            app._enforce_history_storage_budget(
                trigger_label="settings update",
                interactive=True,
            )
        app._sync_application_isrc_registry()
        app._update_add_data_generated_fields()
        app._refresh_history_actions()
        if show_confirmation:
            app._play_notice_sound()
            QMessageBox.information(app, "Settings Saved", "Application settings updated.")
    return changed_count


def open_settings_dialog(app, initial_focus: str | None = None):
    before_values = app._current_settings_values()
    dlg = ApplicationSettingsDialog(
        window_title=before_values["window_title"],
        effective_window_title=before_values["effective_window_title"],
        owner_company_name=before_values["owner_company_name"],
        icon_path=before_values["icon_path"],
        artist_code=before_values["artist_code"],
        auto_snapshot_enabled=before_values["auto_snapshot_enabled"],
        auto_snapshot_interval_minutes=before_values["auto_snapshot_interval_minutes"],
        isrc_prefix=before_values["isrc_prefix"],
        sena_number=before_values["sena_number"],
        btw_number=before_values["btw_number"],
        buma_relatie_nummer=before_values["buma_relatie_nummer"],
        buma_ipi=before_values["buma_ipi"],
        owner_party_settings=before_values["owner_party_settings"],
        gs1_template_asset=before_values["gs1_template_asset"],
        gs1_contracts_csv_path=before_values["gs1_contracts_csv_path"],
        gs1_contract_entries=before_values["gs1_contract_entries"],
        gs1_active_contract_number=before_values["gs1_active_contract_number"],
        gs1_target_market=before_values["gs1_target_market"],
        gs1_language=before_values["gs1_language"],
        gs1_brand=before_values["gs1_brand"],
        gs1_subbrand=before_values["gs1_subbrand"],
        gs1_packaging_type=before_values["gs1_packaging_type"],
        gs1_product_classification=before_values["gs1_product_classification"],
        theme_settings=before_values["theme_settings"],
        stored_themes=before_values["theme_library"],
        blob_icon_settings=before_values["blob_icon_settings"],
        startup_sound_enabled=before_values["startup_sound_enabled"],
        app_sound_settings=before_values["app_sound_settings"],
        current_profile_path=getattr(app, "current_db_path", ""),
        history_retention_mode=before_values["history_retention_mode"],
        history_auto_cleanup_enabled=before_values["history_auto_cleanup_enabled"],
        history_storage_budget_mb=before_values["history_storage_budget_mb"],
        history_auto_snapshot_keep_latest=before_values["history_auto_snapshot_keep_latest"],
        history_prune_pre_restore_copies_after_days=before_values[
            "history_prune_pre_restore_copies_after_days"
        ],
        party_service=app.party_service,
        parent=app,
    )
    dlg.focus_field(initial_focus)
    if dlg.exec() != QDialog.Accepted:
        return
    try:
        app._apply_settings_changes(before_values, dlg.values(), show_confirmation=True)
    except Exception as e:
        app.logger.exception(f"Settings update failed: {e}")
        app._play_warning_sound()
        QMessageBox.critical(app, "Settings Error", f"Could not save settings:\n{e}")


def export_application_settings_bundle(app):
    if app.conn is None or app.settings_transfer_service is None:
        app._play_warning_sound()
        QMessageBox.warning(app, "Export Settings", "Open a profile first.")
        return
    before_values = app._current_settings_values()
    profile_stem = sanitize_export_basename(
        Path(str(getattr(app, "current_db_path", "") or "")).stem or "profile",
        default_stem="profile",
    )
    suggested_name = (
        f"{profile_stem}_application_settings_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip"
    )
    path, _ = QFileDialog.getSaveFileName(
        app,
        "Export Application Settings",
        str(Path.home() / suggested_name),
        "ZIP Archive (*.zip)",
    )
    if not path:
        return
    try:
        saved_path = app.settings_transfer_service.export_bundle(
            path,
            current_values=before_values,
            app_version=app._app_version_text(),
        )
    except Exception as exc:
        app.logger.exception("Application settings export failed: %s", exc)
        app._play_warning_sound()
        QMessageBox.warning(app, "Export Settings", str(exc))
        return
    app.statusBar().showMessage(f"Settings export saved to {saved_path}", 5000)
    app._play_notice_sound()
    QMessageBox.information(
        app,
        "Export Settings",
        f"Saved the application settings bundle to:\n{saved_path}",
    )


def import_application_settings_bundle(app):
    if app.conn is None or app.settings_transfer_service is None:
        app._play_warning_sound()
        QMessageBox.warning(app, "Import Settings", "Open a profile first.")
        return
    path, _ = QFileDialog.getOpenFileName(
        app,
        "Import Application Settings",
        str(Path.home()),
        "ZIP Archive (*.zip)",
    )
    if not path:
        return
    confirm = QMessageBox.question(
        app,
        "Import Settings",
        "Import the selected settings bundle into the current profile?\n\n"
        "This replaces the current General, GS1, and Theme settings for this profile.",
        QMessageBox.Yes | QMessageBox.No,
    )
    if confirm != QMessageBox.Yes:
        return
    before_values = app._current_settings_values()
    try:
        import_result = app.settings_transfer_service.prepare_import(
            path,
            current_values=before_values,
        )
        changed_count = app._apply_settings_changes(
            before_values,
            import_result.values,
            show_confirmation=False,
        )
    except Exception as exc:
        app.logger.exception("Application settings import failed: %s", exc)
        app._play_warning_sound()
        QMessageBox.warning(app, "Import Settings", str(exc))
        return

    message = (
        "Imported the application settings bundle."
        if changed_count
        else "Imported the application settings bundle. No persisted settings needed to change."
    )
    if import_result.warnings:
        message += "\n\nWarnings:\n" + "\n".join(
            f"- {warning}" for warning in import_result.warnings
        )
    app.statusBar().showMessage("Application settings imported.", 5000)
    app._play_notice_sound()
    QMessageBox.information(app, "Import Settings", message)


def _apply_single_setting_value(app, field_name: str, value: str) -> int:
    before_values = app._current_settings_values()
    after_values = dict(before_values)
    after_values[field_name] = value
    return app._apply_settings_changes(before_values, after_values)
