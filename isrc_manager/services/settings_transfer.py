"""Zip-based export and import helpers for portable application settings bundles."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from zipfile import ZIP_DEFLATED, BadZipFile, ZipFile

from isrc_manager.blob_icons import normalize_blob_icon_settings
from isrc_manager.file_storage import (
    STORAGE_MODE_DATABASE,
    ManagedFileStorage,
    coalesce_filename,
    normalize_storage_mode,
)
from isrc_manager.starter_themes import starter_theme_library, starter_theme_names
from isrc_manager.theme_builder import normalize_theme_settings

from .gs1_models import GS1ContractEntry
from .gs1_settings import GS1SettingsService


class ApplicationSettingsTransferError(Exception):
    """Raised when a settings transfer bundle cannot be exported or imported."""


@dataclass(slots=True)
class ApplicationSettingsImportResult:
    values: dict[str, object]
    warnings: tuple[str, ...] = ()


class ApplicationSettingsTransferService:
    """Packages and restores portable application settings plus stored GS1 artifacts."""

    BUNDLE_FORMAT = "isrc-catalog-manager-settings"
    BUNDLE_VERSION = 1
    SETTINGS_JSON_NAME = "settings.json"

    def __init__(
        self,
        *,
        gs1_settings_service: GS1SettingsService | None,
        data_root: str | Path | None = None,
    ):
        self.gs1_settings_service = gs1_settings_service
        self.data_root = Path(data_root).resolve() if data_root is not None else None
        self._attachment_store = ManagedFileStorage(
            data_root=self.data_root,
            relative_root="settings_transfer_assets",
        )

    def export_bundle(
        self,
        destination_path: str | Path,
        *,
        current_values: dict[str, object],
        app_version: str,
    ) -> Path:
        destination = Path(destination_path).expanduser()
        if destination.suffix.lower() != ".zip":
            destination = destination.with_suffix(".zip")
        destination.parent.mkdir(parents=True, exist_ok=True)

        attachments: dict[str, bytes] = {}
        payload = self._build_export_payload(
            current_values=current_values,
            attachments=attachments,
            app_version=app_version,
        )
        with ZipFile(destination, "w", compression=ZIP_DEFLATED) as archive:
            archive.writestr(
                self.SETTINGS_JSON_NAME,
                json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
            )
            for archive_path, data in attachments.items():
                archive.writestr(archive_path, data)
        return destination

    def prepare_import(
        self,
        source_path: str | Path,
        *,
        current_values: dict[str, object],
    ) -> ApplicationSettingsImportResult:
        source = Path(source_path).expanduser()
        if not source.exists():
            raise ApplicationSettingsTransferError(
                f"The selected settings archive was not found:\n{source}"
            )
        try:
            with ZipFile(source, "r") as archive:
                payload = self._load_payload(archive)
                after_values = dict(current_values or {})
                warnings: list[str] = []

                self._apply_general_import(
                    after_values=after_values,
                    payload=dict(payload.get("general") or {}),
                    archive=archive,
                    warnings=warnings,
                )
                self._apply_theme_import(
                    after_values=after_values,
                    payload=dict(payload.get("theme") or {}),
                )
                self._apply_gs1_import(
                    after_values=after_values,
                    payload=dict(payload.get("gs1") or {}),
                    archive=archive,
                    warnings=warnings,
                )
        except BadZipFile as exc:
            raise ApplicationSettingsTransferError(
                "The selected file is not a valid settings ZIP archive."
            ) from exc
        except KeyError as exc:
            raise ApplicationSettingsTransferError(
                f"The settings archive is missing a required file:\n{exc}"
            ) from exc
        return ApplicationSettingsImportResult(values=after_values, warnings=tuple(warnings))

    def _build_export_payload(
        self,
        *,
        current_values: dict[str, object],
        attachments: dict[str, bytes],
        app_version: str,
    ) -> dict[str, object]:
        general_payload = self._build_general_payload(
            current_values=current_values, attachments=attachments
        )
        gs1_payload = self._build_gs1_payload(attachments=attachments)
        theme_payload = self._build_theme_payload(current_values=current_values)
        return {
            "bundle_format": self.BUNDLE_FORMAT,
            "bundle_version": self.BUNDLE_VERSION,
            "app_version": str(app_version or "").strip(),
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "general": general_payload,
            "gs1": gs1_payload,
            "theme": theme_payload,
        }

    def _build_general_payload(
        self,
        *,
        current_values: dict[str, object],
        attachments: dict[str, bytes],
    ) -> dict[str, object]:
        icon_path = str(current_values.get("icon_path") or "").strip()
        icon_attachment_path = ""
        icon_filename = ""
        if icon_path:
            icon_file = Path(icon_path)
            if icon_file.exists() and icon_file.is_file():
                try:
                    icon_bytes = icon_file.read_bytes()
                except OSError:
                    icon_bytes = b""
                if icon_bytes:
                    icon_filename = coalesce_filename(
                        icon_file.name, default_stem="application-icon"
                    )
                    icon_attachment_path = f"general/icon/{icon_filename}"
                    attachments[icon_attachment_path] = icon_bytes
        return {
            "identity": {
                "window_title_override": str(current_values.get("window_title") or "").strip(),
                "icon_path": icon_path,
                "icon_attachment_path": icon_attachment_path,
                "icon_filename": icon_filename,
            },
            "artist_code": str(current_values.get("artist_code") or "").strip(),
            "registration": {
                "isrc_prefix": str(current_values.get("isrc_prefix") or "").strip(),
                "sena_number": str(current_values.get("sena_number") or "").strip(),
                "btw_number": str(current_values.get("btw_number") or "").strip(),
                "buma_relatie_nummer": str(current_values.get("buma_relatie_nummer") or "").strip(),
                "buma_ipi": str(current_values.get("buma_ipi") or "").strip(),
            },
            "auto_snapshot": {
                "enabled": bool(current_values.get("auto_snapshot_enabled")),
                "interval_minutes": int(current_values.get("auto_snapshot_interval_minutes") or 0),
            },
            "history_retention": {
                "retention_mode": str(current_values.get("history_retention_mode") or "").strip(),
                "auto_cleanup_enabled": bool(current_values.get("history_auto_cleanup_enabled")),
                "storage_budget_mb": int(current_values.get("history_storage_budget_mb") or 0),
                "auto_snapshot_keep_latest": int(
                    current_values.get("history_auto_snapshot_keep_latest") or 0
                ),
                "prune_pre_restore_copies_after_days": int(
                    current_values.get("history_prune_pre_restore_copies_after_days") or 0
                ),
            },
        }

    def _build_theme_payload(self, *, current_values: dict[str, object]) -> dict[str, object]:
        custom_theme_library = {
            str(name): normalize_theme_settings(values)
            for name, values in dict(current_values.get("theme_library") or {}).items()
            if str(name).strip() and str(name) not in set(starter_theme_names())
        }
        return {
            "theme_settings": normalize_theme_settings(current_values.get("theme_settings")),
            "custom_theme_library": custom_theme_library,
            "blob_icon_settings": normalize_blob_icon_settings(
                current_values.get("blob_icon_settings")
            ),
        }

    def _build_gs1_payload(self, *, attachments: dict[str, bytes]) -> dict[str, object]:
        template_payload: dict[str, object] = {
            "present": False,
            "filename": "",
            "storage_mode": STORAGE_MODE_DATABASE,
            "attachment_path": "",
        }
        contracts_payload: dict[str, object] = {
            "present": False,
            "filename": "",
            "attachment_path": "",
            "entries": (),
        }
        if self.gs1_settings_service is None:
            return {
                "profile_defaults": {
                    "contract_number": "",
                    "target_market": "",
                    "language": "",
                    "brand": "",
                    "subbrand": "",
                    "packaging_type": "",
                    "product_classification": "",
                },
                "template": template_payload,
                "contracts": contracts_payload,
            }

        defaults = self.gs1_settings_service.load_profile_defaults()
        template_asset = self.gs1_settings_service.load_template_asset()
        if template_asset is not None:
            template_bytes = self.gs1_settings_service.load_stored_template_bytes()
            if template_bytes:
                template_filename = coalesce_filename(
                    template_asset.filename,
                    default_stem="gs1-template",
                    default_suffix=template_asset.suffix,
                )
                template_attachment_path = f"gs1/template/{template_filename}"
                attachments[template_attachment_path] = template_bytes
                template_payload = {
                    "present": True,
                    "filename": template_filename,
                    "storage_mode": normalize_storage_mode(
                        template_asset.storage_mode,
                        default=STORAGE_MODE_DATABASE,
                    )
                    or STORAGE_MODE_DATABASE,
                    "attachment_path": template_attachment_path,
                }

        contracts = tuple(self.gs1_settings_service.load_contracts())
        contracts_bytes = self.gs1_settings_service.load_stored_contracts_bytes()
        contracts_filename = self.gs1_settings_service.load_stored_contracts_filename()
        contracts_attachment_path = ""
        if contracts_bytes:
            safe_filename = coalesce_filename(
                contracts_filename,
                default_stem="gs1-contracts",
                default_suffix=".csv",
            )
            contracts_attachment_path = f"gs1/contracts/{safe_filename}"
            attachments[contracts_attachment_path] = contracts_bytes
            contracts_filename = safe_filename
        contracts_payload = {
            "present": bool(contracts),
            "filename": str(contracts_filename or "").strip(),
            "attachment_path": contracts_attachment_path,
            "entries": [
                {
                    "contract_number": str(entry.contract_number or "").strip(),
                    "product": str(entry.product or "").strip(),
                    "company_number": str(entry.company_number or "").strip(),
                    "start_number": str(entry.start_number or "").strip(),
                    "end_number": str(entry.end_number or "").strip(),
                    "renewal_date": str(entry.renewal_date or "").strip(),
                    "end_date": str(entry.end_date or "").strip(),
                    "status": str(entry.status or "").strip(),
                    "tier": str(entry.tier or "").strip(),
                }
                for entry in contracts
            ],
        }
        return {
            "profile_defaults": {
                "contract_number": str(defaults.contract_number or "").strip(),
                "target_market": str(defaults.target_market or "").strip(),
                "language": str(defaults.language or "").strip(),
                "brand": str(defaults.brand or "").strip(),
                "subbrand": str(defaults.subbrand or "").strip(),
                "packaging_type": str(defaults.packaging_type or "").strip(),
                "product_classification": str(defaults.product_classification or "").strip(),
            },
            "template": template_payload,
            "contracts": contracts_payload,
        }

    def _load_payload(self, archive: ZipFile) -> dict[str, object]:
        try:
            raw_payload = archive.read(self.SETTINGS_JSON_NAME)
        except KeyError as exc:
            raise ApplicationSettingsTransferError(
                "The selected ZIP file does not contain settings.json."
            ) from exc
        try:
            payload = json.loads(raw_payload.decode("utf-8"))
        except Exception as exc:
            raise ApplicationSettingsTransferError(
                "The settings bundle contains an unreadable settings.json file."
            ) from exc
        if not isinstance(payload, dict):
            raise ApplicationSettingsTransferError("The settings bundle payload is invalid.")
        if str(payload.get("bundle_format") or "").strip() != self.BUNDLE_FORMAT:
            raise ApplicationSettingsTransferError(
                "The selected ZIP file is not a Music Catalog Manager settings bundle."
            )
        bundle_version = int(payload.get("bundle_version") or 0)
        if bundle_version != self.BUNDLE_VERSION:
            raise ApplicationSettingsTransferError(
                f"This settings bundle uses unsupported format version {bundle_version}."
            )
        return payload

    def _apply_general_import(
        self,
        *,
        after_values: dict[str, object],
        payload: dict[str, object],
        archive: ZipFile,
        warnings: list[str],
    ) -> None:
        identity = dict(payload.get("identity") or {})
        icon_path = str(identity.get("icon_path") or "").strip()
        icon_attachment_path = str(identity.get("icon_attachment_path") or "").strip()
        icon_filename = str(identity.get("icon_filename") or "").strip()
        if icon_attachment_path:
            try:
                icon_bytes = archive.read(icon_attachment_path)
            except KeyError as exc:
                raise ApplicationSettingsTransferError(
                    f"The settings bundle is missing the packaged icon attachment:\n{icon_attachment_path}"
                ) from exc
            materialized_icon_path = self._materialize_attachment(
                icon_bytes,
                filename=icon_filename or Path(icon_attachment_path).name,
                subdir="icons",
            )
            if materialized_icon_path:
                icon_path = materialized_icon_path
            else:
                warnings.append(
                    "The bundled application icon could not be restored because managed app storage is not configured."
                )
        elif icon_path:
            warnings.append(
                "The imported settings reference an application icon path, but no icon file was bundled."
            )

        registration = dict(payload.get("registration") or {})
        auto_snapshot = dict(payload.get("auto_snapshot") or {})
        history = dict(payload.get("history_retention") or {})

        after_values["window_title"] = str(identity.get("window_title_override") or "").strip()
        after_values["icon_path"] = icon_path
        after_values["artist_code"] = str(payload.get("artist_code") or "").strip()
        after_values["isrc_prefix"] = str(registration.get("isrc_prefix") or "").strip()
        after_values["sena_number"] = str(registration.get("sena_number") or "").strip()
        after_values["btw_number"] = str(registration.get("btw_number") or "").strip()
        after_values["buma_relatie_nummer"] = str(
            registration.get("buma_relatie_nummer") or ""
        ).strip()
        after_values["buma_ipi"] = str(registration.get("buma_ipi") or "").strip()
        after_values["auto_snapshot_enabled"] = bool(auto_snapshot.get("enabled"))
        after_values["auto_snapshot_interval_minutes"] = int(
            auto_snapshot.get("interval_minutes") or 0
        )
        after_values["history_retention_mode"] = str(history.get("retention_mode") or "").strip()
        after_values["history_auto_cleanup_enabled"] = bool(history.get("auto_cleanup_enabled"))
        after_values["history_storage_budget_mb"] = int(history.get("storage_budget_mb") or 0)
        after_values["history_auto_snapshot_keep_latest"] = int(
            history.get("auto_snapshot_keep_latest") or 0
        )
        after_values["history_prune_pre_restore_copies_after_days"] = int(
            history.get("prune_pre_restore_copies_after_days") or 0
        )

    def _apply_theme_import(
        self,
        *,
        after_values: dict[str, object],
        payload: dict[str, object],
    ) -> None:
        imported_custom_library = {
            str(name): normalize_theme_settings(values)
            for name, values in dict(payload.get("custom_theme_library") or {}).items()
            if str(name).strip()
        }
        merged_library = starter_theme_library()
        merged_library.update(imported_custom_library)
        theme_settings = normalize_theme_settings(payload.get("theme_settings"))
        selected_name = str(theme_settings.get("selected_name") or "").strip()
        if selected_name and selected_name not in merged_library:
            theme_settings["selected_name"] = ""
        after_values["theme_library"] = merged_library
        after_values["theme_settings"] = theme_settings
        after_values["blob_icon_settings"] = normalize_blob_icon_settings(
            payload.get("blob_icon_settings")
        )

    def _apply_gs1_import(
        self,
        *,
        after_values: dict[str, object],
        payload: dict[str, object],
        archive: ZipFile,
        warnings: list[str],
    ) -> None:
        defaults = dict(payload.get("profile_defaults") or {})
        template_payload = dict(payload.get("template") or {})
        contracts_payload = dict(payload.get("contracts") or {})

        after_values["gs1_active_contract_number"] = str(
            defaults.get("contract_number") or ""
        ).strip()
        after_values["gs1_target_market"] = str(defaults.get("target_market") or "").strip()
        after_values["gs1_language"] = str(defaults.get("language") or "").strip()
        after_values["gs1_brand"] = str(defaults.get("brand") or "").strip()
        after_values["gs1_subbrand"] = str(defaults.get("subbrand") or "").strip()
        after_values["gs1_packaging_type"] = str(defaults.get("packaging_type") or "").strip()
        after_values["gs1_product_classification"] = str(
            defaults.get("product_classification") or ""
        ).strip()

        template_present = bool(template_payload.get("present"))
        after_values["gs1_template_import_bytes"] = None
        after_values["gs1_template_import_filename"] = ""
        after_values["gs1_template_import_path"] = ""
        after_values["gs1_template_clear_existing"] = not template_present
        if template_present:
            attachment_path = str(template_payload.get("attachment_path") or "").strip()
            filename = str(template_payload.get("filename") or "").strip()
            if not attachment_path:
                raise ApplicationSettingsTransferError(
                    "The imported settings bundle references a GS1 template without an attachment path."
                )
            try:
                after_values["gs1_template_import_bytes"] = archive.read(attachment_path)
            except KeyError as exc:
                raise ApplicationSettingsTransferError(
                    f"The settings bundle is missing the packaged GS1 template:\n{attachment_path}"
                ) from exc
            after_values["gs1_template_import_filename"] = filename or Path(attachment_path).name
            after_values["gs1_template_storage_mode"] = normalize_storage_mode(
                template_payload.get("storage_mode"),
                default=STORAGE_MODE_DATABASE,
            )

        contract_entries = tuple(
            GS1ContractEntry(
                contract_number=str(item.get("contract_number") or "").strip(),
                product=str(item.get("product") or "").strip(),
                company_number=str(item.get("company_number") or "").strip(),
                start_number=str(item.get("start_number") or "").strip(),
                end_number=str(item.get("end_number") or "").strip(),
                renewal_date=str(item.get("renewal_date") or "").strip(),
                end_date=str(item.get("end_date") or "").strip(),
                status=str(item.get("status") or "").strip(),
                tier=str(item.get("tier") or "").strip(),
            )
            for item in list(contracts_payload.get("entries") or [])
            if str(item.get("contract_number") or "").strip()
        )
        after_values["gs1_contract_entries"] = contract_entries
        after_values["gs1_contracts_csv_path"] = ""
        after_values["gs1_contracts_csv_bytes"] = None
        after_values["gs1_contracts_csv_filename"] = str(
            contracts_payload.get("filename") or ""
        ).strip()
        contracts_present = bool(contracts_payload.get("present")) or bool(contract_entries)
        if contracts_present:
            attachment_path = str(contracts_payload.get("attachment_path") or "").strip()
            if attachment_path:
                try:
                    after_values["gs1_contracts_csv_bytes"] = archive.read(attachment_path)
                except KeyError as exc:
                    raise ApplicationSettingsTransferError(
                        f"The settings bundle is missing the packaged GTIN contracts CSV:\n{attachment_path}"
                    ) from exc
            elif contract_entries:
                warnings.append(
                    "The imported settings bundle did not include the GTIN contracts CSV attachment, so a canonical CSV will be regenerated from the stored contract entries."
                )

    def _materialize_attachment(
        self,
        data: bytes,
        *,
        filename: str,
        subdir: str,
    ) -> str:
        if not data:
            return ""
        try:
            stored_path = self._attachment_store.write_bytes(
                data,
                filename=coalesce_filename(filename, default_stem="attachment"),
                subdir=subdir,
            )
        except Exception:
            return ""
        resolved = self._attachment_store.resolve(stored_path)
        return str(resolved) if resolved is not None else ""
