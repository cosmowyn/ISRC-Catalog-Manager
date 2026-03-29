"""Master logical catalog transfer export/import orchestration."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from importlib import metadata
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from isrc_manager.contract_templates import (
    ContractTemplatePayload,
    ContractTemplatePlaceholderBindingPayload,
    ContractTemplateRevisionPayload,
    ContractTemplateService,
)
from isrc_manager.file_storage import coalesce_filename
from isrc_manager.services.licenses import LicenseService

from .models import ExchangeImportOptions, ExchangeImportReport, ExchangeInspection
from .repertoire_service import (
    RepertoireExchangeService,
    RepertoireImportInspection,
    RepertoireImportOptions,
    RepertoireImportResult,
)
from .service import ExchangeService

MASTER_TRANSFER_DOCUMENT_TYPE = "master_transfer_package"
MASTER_TRANSFER_PACKAGE_FORMAT = "logical_catalog_transfer"
MASTER_TRANSFER_FORMAT_VERSION = 1
MASTER_TRANSFER_MANIFEST = "manifest.json"
MASTER_TRANSFER_APP_NAME = "ISRC Catalog Manager"
LICENSE_SECTION_SCHEMA_VERSION = 1
CONTRACT_TEMPLATE_SECTION_SCHEMA_VERSION = 1

CATALOG_SECTION_ID = "catalog"
REPERTOIRE_SECTION_ID = "repertoire"
LICENSES_SECTION_ID = "licenses"
CONTRACT_TEMPLATES_SECTION_ID = "contract_templates"

KNOWN_SECTION_IDS = {
    CATALOG_SECTION_ID,
    REPERTOIRE_SECTION_ID,
    LICENSES_SECTION_ID,
    CONTRACT_TEMPLATES_SECTION_ID,
}


def _app_version_text() -> str:
    for package_name in ("isrc-catalog-manager", "ISRC Catalog Manager"):
        try:
            return metadata.version(package_name)
        except metadata.PackageNotFoundError:
            continue
        except Exception:
            break
    return "3.1.0"


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _json_dumps(payload: object) -> str:
    return json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True)


@dataclass(slots=True)
class MasterTransferSection:
    section_id: str
    label: str
    artifact_path: str
    payload_kind: str
    section_format: str
    schema_version: int
    required: bool
    depends_on: list[str]
    entity_counts: dict[str, int]
    artifact_sha256: str
    artifact_size_bytes: int


@dataclass(slots=True)
class MasterTransferExportResult:
    path: str
    app_version: str
    exported_at: str
    sections: list[MasterTransferSection]
    warnings: list[str] = field(default_factory=list)
    manifest: dict[str, object] = field(default_factory=dict)


@dataclass(slots=True)
class MasterTransferInspection:
    file_path: str
    app_version: str
    exported_at: str
    sections: list[MasterTransferSection]
    warnings: list[str]
    summary_lines: list[str]
    preview_rows: list[dict[str, object]]
    manifest: dict[str, object]
    catalog_inspection: ExchangeInspection
    catalog_dry_run: ExchangeImportReport
    repertoire_inspection: RepertoireImportInspection


@dataclass(slots=True)
class MasterTransferImportResult:
    file_path: str
    app_version: str
    exported_at: str
    warnings: list[str]
    manifest: dict[str, object]
    repertoire_party_phase: RepertoireImportResult
    catalog_report: ExchangeImportReport
    repertoire_report: RepertoireImportResult
    imported_licenses: int = 0
    imported_contract_templates: int = 0
    imported_template_revisions: int = 0


class MasterTransferService:
    """Packages and rehydrates the logical catalog transfer bundle."""

    def __init__(
        self,
        *,
        exchange_service: ExchangeService,
        repertoire_exchange_service: RepertoireExchangeService,
        license_service: LicenseService | None = None,
        contract_template_service: ContractTemplateService | None = None,
        app_version: str | None = None,
    ) -> None:
        self.exchange_service = exchange_service
        self.repertoire_exchange_service = repertoire_exchange_service
        self.license_service = license_service
        self.contract_template_service = contract_template_service
        self.conn: sqlite3.Connection = exchange_service.conn
        self.app_version = str(app_version or _app_version_text())

    @staticmethod
    def _report_progress(
        progress_callback, value: int, message: str, *, maximum: int = 100
    ) -> None:
        if progress_callback is None:
            return
        progress_callback(int(value), int(maximum), str(message or ""))

    @staticmethod
    def _scaled_progress(progress_callback, *, start: int, end: int):
        span = max(0, end - start)

        def _callback(value: int, maximum: int, message: str) -> None:
            if progress_callback is None:
                return
            clean_maximum = max(1, int(maximum or 100))
            ratio = max(0.0, min(1.0, float(int(value or 0)) / float(clean_maximum)))
            scaled_value = int(round(start + (span * ratio)))
            progress_callback(scaled_value, 100, str(message or ""))

        return _callback

    def export_package(
        self,
        path: str | Path,
        *,
        progress_callback=None,
        cancel_callback=None,
    ) -> MasterTransferExportResult:
        output_path = Path(path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        exported_at = _utc_timestamp()

        with tempfile.TemporaryDirectory(prefix="master-transfer-export-") as temp_dir:
            root = Path(temp_dir)
            sections_dir = root / "sections"
            sections_dir.mkdir(parents=True, exist_ok=True)

            self._report_progress(progress_callback, 4, "Building catalog exchange section...")
            catalog_path = sections_dir / CATALOG_SECTION_ID / "package.zip"
            catalog_path.parent.mkdir(parents=True, exist_ok=True)
            self.exchange_service.export_package(
                catalog_path,
                progress_callback=self._scaled_progress(progress_callback, start=4, end=34),
            )
            if cancel_callback is not None:
                cancel_callback()

            self._report_progress(progress_callback, 34, "Building Contracts and Rights section...")
            repertoire_path = sections_dir / REPERTOIRE_SECTION_ID / "package.zip"
            repertoire_path.parent.mkdir(parents=True, exist_ok=True)
            self.repertoire_exchange_service.export_package(
                repertoire_path,
                progress_callback=self._scaled_progress(progress_callback, start=34, end=62),
            )
            if cancel_callback is not None:
                cancel_callback()

            self._report_progress(progress_callback, 62, "Building license transfer section...")
            licenses_payload_path = sections_dir / LICENSES_SECTION_ID / "licenses.json"
            licenses_payload_path.parent.mkdir(parents=True, exist_ok=True)
            license_rows = self._write_license_section(
                licenses_payload_path,
                progress_callback=self._scaled_progress(progress_callback, start=62, end=76),
            )
            if cancel_callback is not None:
                cancel_callback()

            self._report_progress(
                progress_callback, 76, "Building contract template transfer section..."
            )
            template_payload_path = sections_dir / CONTRACT_TEMPLATES_SECTION_ID / "templates.json"
            template_payload_path.parent.mkdir(parents=True, exist_ok=True)
            template_counts = self._write_contract_template_section(
                template_payload_path,
                progress_callback=self._scaled_progress(progress_callback, start=76, end=88),
            )

            sections = [
                self._build_catalog_section(catalog_path),
                self._build_repertoire_section(repertoire_path),
                self._build_license_section_summary(licenses_payload_path, license_rows),
                self._build_contract_template_section_summary(
                    template_payload_path,
                    template_counts=template_counts,
                ),
            ]
            omitted_sections = self._omitted_sections()
            export_warnings = self._dedupe_preserve_order(
                [
                    *self._section_manifest_warnings(catalog_path),
                    *self._section_manifest_warnings(repertoire_path),
                ]
            )
            manifest = self._build_manifest(
                exported_at=exported_at,
                sections=sections,
                files=self._build_file_manifest(root),
                omitted_sections=omitted_sections,
                warnings=export_warnings,
            )

            self._report_progress(progress_callback, 90, "Writing master transfer manifest...")
            manifest_path = root / MASTER_TRANSFER_MANIFEST
            manifest_path.write_text(_json_dumps(manifest), encoding="utf-8")

            self._report_progress(progress_callback, 95, "Assembling master transfer package...")
            with ZipFile(output_path, "w", compression=ZIP_DEFLATED) as archive:
                for file_path in sorted(path for path in root.rglob("*") if path.is_file()):
                    archive.write(file_path, arcname=file_path.relative_to(root).as_posix())

        warnings = self._manifest_warnings(manifest)
        self._report_progress(progress_callback, 100, "Master transfer export package written.")
        return MasterTransferExportResult(
            path=str(output_path),
            app_version=self.app_version,
            exported_at=exported_at,
            sections=sections,
            warnings=warnings,
            manifest=manifest,
        )

    def inspect_package(
        self,
        path: str | Path,
        *,
        progress_callback=None,
        cancel_callback=None,
    ) -> MasterTransferInspection:
        with tempfile.TemporaryDirectory(prefix="master-transfer-inspect-") as temp_dir:
            root = Path(temp_dir)
            self._report_progress(progress_callback, 4, "Opening master transfer package...")
            self._safe_extract_zip(path, root)
            manifest = self._load_manifest_from_root(root)
            self._verify_manifest_files(manifest, root)
            sections = self._manifest_sections(manifest)

            self._report_progress(progress_callback, 12, "Inspecting catalog section...")
            catalog_path = root / self._section_artifact_path(manifest, CATALOG_SECTION_ID)
            catalog_inspection = self.exchange_service.inspect_package(
                catalog_path,
                progress_callback=self._scaled_progress(progress_callback, start=12, end=26),
                cancel_callback=cancel_callback,
            )

            self._report_progress(progress_callback, 26, "Running catalog dry-run review...")
            catalog_dry_run = self.exchange_service.import_package(
                catalog_path,
                options=ExchangeImportOptions(
                    mode="dry_run",
                    create_missing_custom_fields=True,
                    preview_apply_mode="create",
                ),
                progress_callback=self._scaled_progress(progress_callback, start=26, end=46),
                cancel_callback=cancel_callback,
            )

            self._report_progress(
                progress_callback, 46, "Inspecting Contracts and Rights section..."
            )
            repertoire_path = root / self._section_artifact_path(manifest, REPERTOIRE_SECTION_ID)
            repertoire_inspection = self.repertoire_exchange_service.inspect_package(
                repertoire_path,
                progress_callback=self._scaled_progress(progress_callback, start=46, end=68),
                cancel_callback=cancel_callback,
            )

            self._report_progress(progress_callback, 68, "Inspecting license transfer section...")
            license_rows = self._read_license_rows(
                root / self._section_artifact_path(manifest, LICENSES_SECTION_ID)
            )

            self._report_progress(
                progress_callback,
                78,
                "Inspecting contract template transfer section...",
            )
            template_payload = self._read_json_object(
                root / self._section_artifact_path(manifest, CONTRACT_TEMPLATES_SECTION_ID)
            )

        warnings = self._dedupe_preserve_order(
            [
                *self._manifest_warnings(manifest),
                *self._unknown_section_warnings(manifest),
                *self._target_population_warnings(),
                *catalog_inspection.warnings,
                *catalog_dry_run.warnings,
                *repertoire_inspection.warnings,
            ]
        )
        summary_lines = self._inspection_summary_lines(manifest, sections)
        preview_rows = self._build_preview_rows(
            catalog_inspection=catalog_inspection,
            repertoire_inspection=repertoire_inspection,
            license_rows=license_rows,
            template_payload=template_payload,
        )
        self._report_progress(progress_callback, 100, "Master transfer preview ready.")
        return MasterTransferInspection(
            file_path=str(path),
            app_version=str(manifest.get("app_version") or ""),
            exported_at=str(manifest.get("exported_at") or ""),
            sections=sections,
            warnings=warnings,
            summary_lines=summary_lines,
            preview_rows=preview_rows,
            manifest=manifest,
            catalog_inspection=catalog_inspection,
            catalog_dry_run=catalog_dry_run,
            repertoire_inspection=repertoire_inspection,
        )

    def import_package(
        self,
        path: str | Path,
        *,
        progress_callback=None,
        cancel_callback=None,
    ) -> MasterTransferImportResult:
        with tempfile.TemporaryDirectory(prefix="master-transfer-import-") as temp_dir:
            root = Path(temp_dir)
            self._report_progress(progress_callback, 4, "Opening master transfer package...")
            self._safe_extract_zip(path, root)
            manifest = self._load_manifest_from_root(root)
            self._verify_manifest_files(manifest, root)

            self._report_progress(
                progress_callback,
                8,
                "Seeding Party references from Contracts and Rights...",
            )
            repertoire_path = root / self._section_artifact_path(manifest, REPERTOIRE_SECTION_ID)
            repertoire_party_phase = self.repertoire_exchange_service.import_package(
                repertoire_path,
                options=RepertoireImportOptions(phase="parties_only"),
                progress_callback=self._scaled_progress(progress_callback, start=8, end=22),
                cancel_callback=cancel_callback,
            )

            if cancel_callback is not None:
                cancel_callback()
            self._report_progress(progress_callback, 22, "Importing catalog section...")
            catalog_path = root / self._section_artifact_path(manifest, CATALOG_SECTION_ID)
            catalog_report = self.exchange_service.import_package(
                catalog_path,
                options=ExchangeImportOptions(
                    mode="create",
                    create_missing_custom_fields=True,
                ),
                progress_callback=self._scaled_progress(progress_callback, start=22, end=58),
                cancel_callback=cancel_callback,
            )
            self._raise_for_catalog_failures(catalog_report)

            if cancel_callback is not None:
                cancel_callback()
            self._report_progress(progress_callback, 58, "Importing license section...")
            imported_licenses = self._import_license_section(
                root / self._section_artifact_path(manifest, LICENSES_SECTION_ID),
                track_id_map=catalog_report.source_track_id_map,
                progress_callback=self._scaled_progress(progress_callback, start=58, end=70),
                cancel_callback=cancel_callback,
            )

            if cancel_callback is not None:
                cancel_callback()
            self._report_progress(progress_callback, 70, "Rehydrating repertoire relationships...")
            repertoire_report = self.repertoire_exchange_service.import_package(
                repertoire_path,
                options=RepertoireImportOptions(
                    phase="remaining",
                    source_party_id_map=repertoire_party_phase.source_party_id_map,
                    source_track_id_map=catalog_report.source_track_id_map,
                    source_release_id_map=catalog_report.source_release_id_map,
                ),
                progress_callback=self._scaled_progress(progress_callback, start=70, end=90),
                cancel_callback=cancel_callback,
            )

            if cancel_callback is not None:
                cancel_callback()
            self._report_progress(progress_callback, 90, "Importing contract templates...")
            imported_template_counts = self._import_contract_template_section(
                root / self._section_artifact_path(manifest, CONTRACT_TEMPLATES_SECTION_ID),
                progress_callback=self._scaled_progress(progress_callback, start=90, end=98),
                cancel_callback=cancel_callback,
            )

        warnings = self._dedupe_preserve_order(
            [
                *self._manifest_warnings(manifest),
                *catalog_report.warnings,
            ]
        )
        self._report_progress(progress_callback, 100, "Master transfer import complete.")
        return MasterTransferImportResult(
            file_path=str(path),
            app_version=str(manifest.get("app_version") or ""),
            exported_at=str(manifest.get("exported_at") or ""),
            warnings=warnings,
            manifest=manifest,
            repertoire_party_phase=repertoire_party_phase,
            catalog_report=catalog_report,
            repertoire_report=repertoire_report,
            imported_licenses=imported_licenses,
            imported_contract_templates=int(imported_template_counts.get("templates") or 0),
            imported_template_revisions=int(imported_template_counts.get("revisions") or 0),
        )

    def _build_manifest(
        self,
        *,
        exported_at: str,
        sections: list[MasterTransferSection],
        files: list[dict[str, object]],
        omitted_sections: list[dict[str, str]],
        warnings: list[str] | None = None,
    ) -> dict[str, object]:
        return {
            "document_type": MASTER_TRANSFER_DOCUMENT_TYPE,
            "package_format": MASTER_TRANSFER_PACKAGE_FORMAT,
            "package_format_version": MASTER_TRANSFER_FORMAT_VERSION,
            "app_name": MASTER_TRANSFER_APP_NAME,
            "app_version": self.app_version,
            "exported_at": exported_at,
            "compatibility": {
                "minimum_reader_manifest_version": 1,
                "unknown_fields_policy": "ignore",
                "unknown_optional_sections_policy": "warn_skip",
                "unknown_required_sections_policy": "error",
            },
            "import_guidance": {
                "requires_preview": True,
                "requires_explicit_confirmation": True,
                "section_order": [
                    CATALOG_SECTION_ID,
                    LICENSES_SECTION_ID,
                    REPERTOIRE_SECTION_ID,
                    CONTRACT_TEMPLATES_SECTION_ID,
                ],
                "stages": [
                    {
                        "stage_id": "repertoire_parties",
                        "section_id": REPERTOIRE_SECTION_ID,
                        "phase": "parties_only",
                        "description": "Seed Party identities before catalog and repertoire links.",
                    },
                    {
                        "stage_id": "catalog",
                        "section_id": CATALOG_SECTION_ID,
                        "phase": "full",
                        "mode": "create",
                        "description": "Import the catalog package through the governed catalog importer.",
                    },
                    {
                        "stage_id": "licenses",
                        "section_id": LICENSES_SECTION_ID,
                        "phase": "full",
                        "description": "Reattach license PDFs through the license service.",
                    },
                    {
                        "stage_id": "repertoire_remaining",
                        "section_id": REPERTOIRE_SECTION_ID,
                        "phase": "remaining",
                        "description": "Import Works, Contracts, Rights, and Assets with remapped ids.",
                    },
                    {
                        "stage_id": "contract_templates",
                        "section_id": CONTRACT_TEMPLATES_SECTION_ID,
                        "phase": "full",
                        "description": "Recreate template families and import revision source files.",
                    },
                ],
                "reuses_current_import_logic": {
                    CATALOG_SECTION_ID: "exchange_service.import_package",
                    REPERTOIRE_SECTION_ID: "repertoire_exchange_service.import_package",
                    LICENSES_SECTION_ID: "license_service.add_license",
                    CONTRACT_TEMPLATES_SECTION_ID: (
                        "contract_template_service.create_template + "
                        "contract_template_service.import_revision_from_bytes"
                    ),
                },
            },
            "sections": [
                {
                    "section_id": section.section_id,
                    "label": section.label,
                    "artifact_path": section.artifact_path,
                    "payload_kind": section.payload_kind,
                    "section_format": section.section_format,
                    "schema_version": int(section.schema_version),
                    "required": bool(section.required),
                    "depends_on": list(section.depends_on),
                    "entity_counts": dict(section.entity_counts),
                    "artifact_sha256": section.artifact_sha256,
                    "artifact_size_bytes": int(section.artifact_size_bytes),
                }
                for section in sections
            ],
            "files": files,
            "warnings": list(warnings or []),
            "omitted_sections": omitted_sections,
        }

    def _build_catalog_section(self, package_path: Path) -> MasterTransferSection:
        payload = self._read_zip_json(package_path, "manifest.json")
        packaged_media_index = payload.get("packaged_media_index")
        media_count = len(packaged_media_index) if isinstance(packaged_media_index, dict) else 0
        return MasterTransferSection(
            section_id=CATALOG_SECTION_ID,
            label="Catalog Exchange Package",
            artifact_path=f"sections/{CATALOG_SECTION_ID}/package.zip",
            payload_kind="zip",
            section_format="catalog_exchange_package",
            schema_version=int(payload.get("schema_version") or 0),
            required=True,
            depends_on=[],
            entity_counts={
                "tracks": len(payload.get("rows") or []),
                "packaged_media": media_count,
            },
            artifact_sha256=self._sha256_file(package_path),
            artifact_size_bytes=package_path.stat().st_size,
        )

    def _build_repertoire_section(self, package_path: Path) -> MasterTransferSection:
        payload = self._read_zip_json(package_path, "manifest.json")
        return MasterTransferSection(
            section_id=REPERTOIRE_SECTION_ID,
            label="Contracts and Rights Package",
            artifact_path=f"sections/{REPERTOIRE_SECTION_ID}/package.zip",
            payload_kind="zip",
            section_format="repertoire_package",
            schema_version=int(payload.get("schema_version") or 0),
            required=True,
            depends_on=[CATALOG_SECTION_ID],
            entity_counts={
                "parties": len(payload.get("parties") or []),
                "works": len(payload.get("works") or []),
                "contracts": len(payload.get("contracts") or []),
                "rights": len(payload.get("rights") or []),
                "assets": len(payload.get("assets") or []),
            },
            artifact_sha256=self._sha256_file(package_path),
            artifact_size_bytes=package_path.stat().st_size,
        )

    def _write_license_section(
        self, payload_path: Path, *, progress_callback=None
    ) -> list[dict[str, object]]:
        if self.license_service is None and self._table_row_count("Licenses") > 0:
            raise ValueError("License service is unavailable for logical transfer export.")
        rows: list[dict[str, object]] = []
        source_rows = (
            list(self.license_service.list_rows()) if self.license_service is not None else []
        )
        total_rows = max(len(source_rows), 1)
        for index, item in enumerate(source_rows, start=1):
            self._report_progress(
                progress_callback,
                int(((index - 1) / total_rows) * 100),
                f"Packaging license {index} of {len(source_rows)}...",
            )
            record = self.license_service.fetch_license(item.record_id)
            if record is None:
                raise ValueError(f"License record {item.record_id} disappeared during export.")
            data, mime_type = self.license_service.fetch_license_bytes(item.record_id)
            filename = coalesce_filename(
                record.filename,
                default_stem=f"license-{item.record_id}",
                default_suffix=".pdf",
            )
            relative_file = Path("files") / f"{int(item.record_id)}_{filename}"
            absolute_file = payload_path.parent / relative_file
            absolute_file.parent.mkdir(parents=True, exist_ok=True)
            absolute_file.write_bytes(data)
            rows.append(
                {
                    "source_license_id": int(item.record_id),
                    "track_id": int(record.track_id),
                    "licensee_name": str(item.licensee or ""),
                    "track_title": str(item.track_title or ""),
                    "uploaded_at": str(item.uploaded_at or ""),
                    "filename": filename,
                    "storage_mode": str(record.storage_mode or "").strip() or None,
                    "mime_type": str(mime_type or record.mime_type or "").strip()
                    or "application/pdf",
                    "size_bytes": len(data),
                    "file_path": relative_file.as_posix(),
                }
            )
        payload_path.write_text(
            _json_dumps(
                {
                    "schema_version": LICENSE_SECTION_SCHEMA_VERSION,
                    "rows": rows,
                }
            ),
            encoding="utf-8",
        )
        return rows

    def _build_license_section_summary(
        self,
        payload_path: Path,
        rows: list[dict[str, object]],
    ) -> MasterTransferSection:
        return MasterTransferSection(
            section_id=LICENSES_SECTION_ID,
            label="License Archive",
            artifact_path=f"sections/{LICENSES_SECTION_ID}/licenses.json",
            payload_kind="file",
            section_format="license_archive_json",
            schema_version=LICENSE_SECTION_SCHEMA_VERSION,
            required=False,
            depends_on=[CATALOG_SECTION_ID],
            entity_counts={"licenses": len(rows)},
            artifact_sha256=self._sha256_file(payload_path),
            artifact_size_bytes=payload_path.stat().st_size,
        )

    def _write_contract_template_section(
        self,
        payload_path: Path,
        *,
        progress_callback=None,
    ) -> dict[str, int]:
        if (
            self.contract_template_service is None
            and self._table_row_count("ContractTemplates") > 0
        ):
            raise ValueError(
                "Contract template service is unavailable for logical transfer export."
            )

        templates_payload: list[dict[str, object]] = []
        template_count = 0
        revision_count = 0
        templates = (
            sorted(
                self.contract_template_service.list_templates(include_archived=True),
                key=lambda item: item.template_id,
            )
            if self.contract_template_service is not None
            else []
        )
        total_templates = max(len(templates), 1)
        for index, template in enumerate(templates, start=1):
            self._report_progress(
                progress_callback,
                int(((index - 1) / total_templates) * 100),
                f"Packaging contract template {index} of {len(templates)}...",
            )
            template_count += 1
            template_payload = template.to_dict()
            revisions_payload: list[dict[str, object]] = []
            revisions = sorted(
                self.contract_template_service.list_revisions(template.template_id),
                key=lambda item: item.revision_id,
            )
            for revision in revisions:
                revision_count += 1
                source_bytes = self.contract_template_service.load_revision_source_bytes(
                    revision.revision_id
                )
                filename = coalesce_filename(
                    revision.source_filename,
                    default_stem=f"template-revision-{revision.revision_id}",
                )
                relative_file = (
                    Path("files")
                    / f"template_{int(template.template_id)}"
                    / f"revision_{int(revision.revision_id)}_{filename}"
                )
                absolute_file = payload_path.parent / relative_file
                absolute_file.parent.mkdir(parents=True, exist_ok=True)
                absolute_file.write_bytes(source_bytes)
                revision_payload = revision.to_dict()
                revision_payload["file_path"] = relative_file.as_posix()
                revision_payload["bindings"] = [
                    item.to_dict()
                    for item in self.contract_template_service.list_placeholder_bindings(
                        revision.revision_id
                    )
                ]
                revision_payload["placeholder_count"] = len(
                    self.contract_template_service.list_placeholders(revision.revision_id)
                )
                revisions_payload.append(revision_payload)
            template_payload["revisions"] = revisions_payload
            templates_payload.append(template_payload)

        payload_path.write_text(
            _json_dumps(
                {
                    "schema_version": CONTRACT_TEMPLATE_SECTION_SCHEMA_VERSION,
                    "templates": templates_payload,
                }
            ),
            encoding="utf-8",
        )
        return {"templates": template_count, "revisions": revision_count}

    def _build_contract_template_section_summary(
        self,
        payload_path: Path,
        *,
        template_counts: dict[str, int],
    ) -> MasterTransferSection:
        return MasterTransferSection(
            section_id=CONTRACT_TEMPLATES_SECTION_ID,
            label="Contract Templates",
            artifact_path=f"sections/{CONTRACT_TEMPLATES_SECTION_ID}/templates.json",
            payload_kind="file",
            section_format="contract_templates_json",
            schema_version=CONTRACT_TEMPLATE_SECTION_SCHEMA_VERSION,
            required=False,
            depends_on=[],
            entity_counts={
                "templates": int(template_counts.get("templates") or 0),
                "revisions": int(template_counts.get("revisions") or 0),
            },
            artifact_sha256=self._sha256_file(payload_path),
            artifact_size_bytes=payload_path.stat().st_size,
        )

    def _import_license_section(
        self,
        payload_path: Path,
        *,
        track_id_map: dict[int, int],
        progress_callback=None,
        cancel_callback=None,
    ) -> int:
        rows = self._read_license_rows(payload_path)
        if self.license_service is None:
            if rows:
                raise ValueError("License service is unavailable for master transfer import.")
            return 0

        total_rows = max(len(rows), 1)
        for index, row in enumerate(rows, start=1):
            if cancel_callback is not None:
                cancel_callback()
            self._report_progress(
                progress_callback,
                int(((index - 1) / total_rows) * 100),
                f"Importing license {index} of {len(rows)}...",
            )
            source_track_id = int(row.get("track_id") or 0)
            target_track_id = self._mapped_identifier(
                source_track_id,
                track_id_map,
                label="license track",
            )
            relative_file = str(row.get("file_path") or "").strip()
            file_path = (payload_path.parent / relative_file).resolve()
            try:
                file_path.relative_to(payload_path.parent.resolve())
            except ValueError as exc:
                raise ValueError(
                    f"License section contains an unsafe file path: {relative_file}"
                ) from exc
            if not file_path.exists():
                raise ValueError(f"License file is missing from the package: {relative_file}")
            self.license_service.add_license(
                track_id=target_track_id,
                licensee_name=str(row.get("licensee_name") or "").strip() or "Imported Licensee",
                source_pdf_path=file_path,
                storage_mode=str(row.get("storage_mode") or "").strip() or None,
            )
        return len(rows)

    def _import_contract_template_section(
        self,
        payload_path: Path,
        *,
        progress_callback=None,
        cancel_callback=None,
    ) -> dict[str, int]:
        payload = self._read_json_object(payload_path)
        templates = [dict(item) for item in list(payload.get("templates") or [])]
        if self.contract_template_service is None:
            if templates:
                raise ValueError(
                    "Contract template service is unavailable for master transfer import."
                )
            return {"templates": 0, "revisions": 0}

        template_count = 0
        revision_count = 0
        total_templates = max(len(templates), 1)
        for index, template in enumerate(templates, start=1):
            if cancel_callback is not None:
                cancel_callback()
            self._report_progress(
                progress_callback,
                int(((index - 1) / total_templates) * 100),
                f"Importing contract template {index} of {len(templates)}...",
            )
            template_record = self.contract_template_service.create_template(
                ContractTemplatePayload(
                    name=str(template.get("name") or "").strip() or "Imported Template",
                    description=str(template.get("description") or "").strip() or None,
                    template_family=str(template.get("template_family") or "contract").strip()
                    or "contract",
                    source_format=str(template.get("source_format") or "").strip() or None,
                )
            )
            template_count += 1
            revision_id_map: dict[int, int] = {}
            for revision in sorted(
                [dict(item) for item in list(template.get("revisions") or [])],
                key=lambda item: int(item.get("revision_id") or 0),
            ):
                if cancel_callback is not None:
                    cancel_callback()
                relative_file = str(revision.get("file_path") or "").strip()
                revision_file = (payload_path.parent / relative_file).resolve()
                try:
                    revision_file.relative_to(payload_path.parent.resolve())
                except ValueError as exc:
                    raise ValueError(
                        f"Contract template section contains an unsafe file path: {relative_file}"
                    ) from exc
                if not revision_file.exists():
                    raise ValueError(f"Contract template revision file is missing: {relative_file}")
                import_result = self.contract_template_service.import_revision_from_bytes(
                    template_record.template_id,
                    revision_file.read_bytes(),
                    payload=ContractTemplateRevisionPayload(
                        revision_label=str(revision.get("revision_label") or "").strip() or None,
                        source_filename=str(revision.get("source_filename") or "").strip()
                        or revision_file.name,
                        source_mime_type=str(revision.get("source_mime_type") or "").strip()
                        or None,
                        source_format=str(revision.get("source_format") or "").strip() or None,
                        source_path=str(revision.get("source_path") or "").strip() or None,
                        storage_mode=str(revision.get("storage_mode") or "").strip() or None,
                    ),
                    bindings=[
                        ContractTemplatePlaceholderBindingPayload(
                            canonical_symbol=str(item.get("canonical_symbol") or "").strip(),
                            resolver_kind=str(item.get("resolver_kind") or "").strip() or None,
                            resolver_target=str(item.get("resolver_target") or "").strip() or None,
                            scope_entity_type=str(item.get("scope_entity_type") or "").strip()
                            or None,
                            scope_policy=str(item.get("scope_policy") or "").strip() or None,
                            widget_hint=str(item.get("widget_hint") or "").strip() or None,
                            validation=item.get("validation"),
                            metadata=item.get("metadata"),
                        )
                        for item in list(revision.get("bindings") or [])
                        if str(item.get("canonical_symbol") or "").strip()
                    ],
                    activate_if_ready=False,
                )
                revision_count += 1
                source_revision_id = int(revision.get("revision_id") or 0)
                if source_revision_id > 0:
                    revision_id_map[source_revision_id] = int(import_result.revision.revision_id)

            active_source_revision_id = int(template.get("active_revision_id") or 0)
            if active_source_revision_id > 0 and active_source_revision_id in revision_id_map:
                self.contract_template_service.set_active_revision(
                    int(revision_id_map[active_source_revision_id])
                )
            if bool(template.get("archived")):
                self.contract_template_service.archive_template(
                    template_record.template_id,
                    archived=True,
                )
        return {"templates": template_count, "revisions": revision_count}

    @staticmethod
    def _safe_extract_zip(path: str | Path, target_dir: Path) -> None:
        target_root = target_dir.resolve()
        with ZipFile(path, "r") as archive:
            for member in archive.infolist():
                member_name = str(member.filename or "")
                destination = (target_root / member_name).resolve()
                try:
                    destination.relative_to(target_root)
                except ValueError as exc:
                    raise ValueError(f"ZIP package contains an unsafe path: {member_name}") from exc
                if member.is_dir():
                    destination.mkdir(parents=True, exist_ok=True)
                    continue
                destination.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(member, "r") as source, destination.open("wb") as target:
                    target.write(source.read())

    @staticmethod
    def _read_json_object(path: str | Path) -> dict[str, object]:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError(f"{Path(path).name} must contain a JSON object.")
        return payload

    def _load_manifest_from_root(self, root: Path) -> dict[str, object]:
        manifest = self._read_json_object(root / MASTER_TRANSFER_MANIFEST)
        if str(manifest.get("document_type") or "").strip() != MASTER_TRANSFER_DOCUMENT_TYPE:
            raise ValueError("Unsupported master transfer package type.")
        if str(manifest.get("package_format") or "").strip() != MASTER_TRANSFER_PACKAGE_FORMAT:
            raise ValueError("Unsupported master transfer package format.")
        version = int(manifest.get("package_format_version") or 0)
        if version > MASTER_TRANSFER_FORMAT_VERSION:
            raise ValueError(
                f"Unsupported master transfer package version {version}. "
                f"Expected {MASTER_TRANSFER_FORMAT_VERSION} or lower."
            )
        return manifest

    def _verify_manifest_files(self, manifest: dict[str, object], root: Path) -> None:
        for item in manifest.get("files") or []:
            entry = dict(item)
            relative_path = str(entry.get("path") or "").strip()
            if not relative_path:
                raise ValueError("Master transfer manifest contains a file entry without a path.")
            absolute_path = (root / relative_path).resolve()
            try:
                absolute_path.relative_to(root.resolve())
            except ValueError as exc:
                raise ValueError(
                    f"Master transfer manifest contains an unsafe file path: {relative_path}"
                ) from exc
            if not absolute_path.exists():
                raise ValueError(f"Master transfer file is missing: {relative_path}")
            expected_hash = str(entry.get("sha256") or "").strip()
            if expected_hash and self._sha256_file(absolute_path) != expected_hash:
                raise ValueError(f"Checksum mismatch for master transfer file: {relative_path}")

    def _section_artifact_path(self, manifest: dict[str, object], section_id: str) -> str:
        for section in manifest.get("sections") or []:
            if str(section.get("section_id") or "").strip() == section_id:
                artifact_path = str(section.get("artifact_path") or "").strip()
                if artifact_path:
                    return artifact_path
                break
        raise ValueError(f"Master transfer manifest does not include section '{section_id}'.")

    @staticmethod
    def _manifest_sections(manifest: dict[str, object]) -> list[MasterTransferSection]:
        sections: list[MasterTransferSection] = []
        for raw_section in manifest.get("sections") or []:
            sections.append(
                MasterTransferSection(
                    section_id=str(raw_section.get("section_id") or ""),
                    label=str(raw_section.get("label") or ""),
                    artifact_path=str(raw_section.get("artifact_path") or ""),
                    payload_kind=str(raw_section.get("payload_kind") or ""),
                    section_format=str(raw_section.get("section_format") or ""),
                    schema_version=int(raw_section.get("schema_version") or 0),
                    required=bool(raw_section.get("required", False)),
                    depends_on=[str(item) for item in list(raw_section.get("depends_on") or [])],
                    entity_counts={
                        str(key): int(value or 0)
                        for key, value in dict(raw_section.get("entity_counts") or {}).items()
                    },
                    artifact_sha256=str(raw_section.get("artifact_sha256") or ""),
                    artifact_size_bytes=int(raw_section.get("artifact_size_bytes") or 0),
                )
            )
        return sections

    def _unknown_section_warnings(self, manifest: dict[str, object]) -> list[str]:
        warnings: list[str] = []
        for raw_section in manifest.get("sections") or []:
            section_id = str(raw_section.get("section_id") or "").strip()
            if not section_id or section_id in KNOWN_SECTION_IDS:
                continue
            if bool(raw_section.get("required")):
                raise ValueError(
                    f"Master transfer package requires an unsupported section '{section_id}'."
                )
            warnings.append(f"Skipped unknown optional section: {section_id}")
        return warnings

    def _inspection_summary_lines(
        self,
        manifest: dict[str, object],
        sections: list[MasterTransferSection],
    ) -> list[str]:
        lines = [
            f"Package format version: {int(manifest.get('package_format_version') or 0)}",
            f"Created by app version: {str(manifest.get('app_version') or '').strip() or 'Unknown'}",
            f"Exported at: {str(manifest.get('exported_at') or '').strip() or 'Unknown'}",
            "Included sections: "
            + ", ".join(section.label for section in sections if section.label),
        ]
        for section in sections:
            if not section.entity_counts:
                continue
            counts_text = ", ".join(
                f"{key.replace('_', ' ')}={value}" for key, value in section.entity_counts.items()
            )
            lines.append(f"{section.label}: {counts_text}")
        target_counts = self._current_target_counts()
        if any(target_counts.values()):
            counts_text = ", ".join(
                f"{key.replace('_', ' ')}={value}" for key, value in target_counts.items() if value
            )
            lines.append("Target profile already contains data: " + counts_text)
        return lines

    def _build_preview_rows(
        self,
        *,
        catalog_inspection: ExchangeInspection,
        repertoire_inspection: RepertoireImportInspection,
        license_rows: list[dict[str, object]],
        template_payload: dict[str, object],
    ) -> list[dict[str, object]]:
        rows: list[dict[str, object]] = []
        for row in catalog_inspection.preview_rows[:6]:
            title = str(row.get("track_title") or "").strip() or "Untitled Track"
            details = [
                value
                for value in (
                    str(row.get("isrc") or "").strip(),
                    str(row.get("artist_name") or "").strip(),
                    str(row.get("release_title") or row.get("album_title") or "").strip(),
                )
                if value
            ]
            rows.append(
                {
                    "Section": "Catalog",
                    "Entity": "Track",
                    "Action": "Import",
                    "Label": title,
                    "Notes": " / ".join(details),
                }
            )
        for row in repertoire_inspection.preview_rows[:10]:
            rows.append(
                {
                    "Section": "Contracts and Rights",
                    "Entity": row.get("Entity"),
                    "Action": row.get("Action"),
                    "Label": row.get("Label"),
                    "Notes": row.get("Notes"),
                }
            )
        for row in license_rows[:4]:
            rows.append(
                {
                    "Section": "License Archive",
                    "Entity": "License",
                    "Action": "Import",
                    "Label": str(row.get("licensee_name") or "").strip() or "Imported License",
                    "Notes": str(row.get("filename") or "").strip(),
                }
            )
        templates = [dict(item) for item in list(template_payload.get("templates") or [])]
        for template in templates[:4]:
            rows.append(
                {
                    "Section": "Contract Templates",
                    "Entity": "Template",
                    "Action": "Import",
                    "Label": str(template.get("name") or "").strip() or "Imported Template",
                    "Notes": f"Revisions: {len(list(template.get('revisions') or []))}",
                }
            )
        return rows

    def _manifest_warnings(self, manifest: dict[str, object]) -> list[str]:
        warnings: list[str] = []
        for warning in manifest.get("warnings") or []:
            clean_warning = str(warning or "").strip()
            if clean_warning:
                warnings.append(clean_warning)
        for item in manifest.get("omitted_sections") or []:
            section = dict(item)
            section_id = str(section.get("section_id") or "").strip()
            reason = str(section.get("reason") or "").strip()
            if section_id and reason:
                warnings.append(f"Omitted from this package: {section_id} - {reason}")
        return warnings

    def _section_manifest_warnings(self, package_path: Path) -> list[str]:
        try:
            payload = self._read_zip_json(package_path, "manifest.json")
        except Exception:
            return []
        warnings: list[str] = []
        for warning in payload.get("warnings") or []:
            clean_warning = str(warning or "").strip()
            if clean_warning:
                warnings.append(clean_warning)
        return warnings

    def _build_file_manifest(self, root: Path) -> list[dict[str, object]]:
        files: list[dict[str, object]] = []
        for file_path in sorted(path for path in root.rglob("*") if path.is_file()):
            relative_path = file_path.relative_to(root).as_posix()
            if relative_path == MASTER_TRANSFER_MANIFEST:
                continue
            files.append(
                {
                    "path": relative_path,
                    "size_bytes": file_path.stat().st_size,
                    "sha256": self._sha256_file(file_path),
                }
            )
        return files

    @staticmethod
    def _read_zip_json(path: Path, member_name: str) -> dict[str, object]:
        with ZipFile(path, "r") as archive:
            try:
                data = archive.read(member_name)
            except KeyError as exc:
                raise ValueError(f"{path.name} does not contain {member_name}.") from exc
        payload = json.loads(data.decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError(f"{member_name} inside {path.name} must contain a JSON object.")
        return payload

    @staticmethod
    def _sha256_file(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _dedupe_preserve_order(values: list[str]) -> list[str]:
        seen: set[str] = set()
        deduped: list[str] = []
        for raw_value in values:
            clean_value = str(raw_value or "").strip()
            if not clean_value or clean_value in seen:
                continue
            seen.add(clean_value)
            deduped.append(clean_value)
        return deduped

    def _raise_for_catalog_failures(self, report: ExchangeImportReport) -> None:
        if report.failed <= 0 and not report.repair_queue_entry_ids:
            return
        summary_bits = [
            f"passed={report.passed}",
            f"failed={report.failed}",
            f"skipped={report.skipped}",
        ]
        if report.repair_queue_entry_ids:
            summary_bits.append(f"repair_queue={len(report.repair_queue_entry_ids)}")
        detail = report.warnings[0] if report.warnings else "Catalog package validation failed."
        raise ValueError(
            "Master transfer import stopped because the catalog section did not import cleanly "
            f"({', '.join(summary_bits)}). First issue: {detail}"
        )

    def _read_license_rows(self, payload_path: Path) -> list[dict[str, object]]:
        payload = self._read_json_object(payload_path)
        version = int(payload.get("schema_version") or 0)
        if version > LICENSE_SECTION_SCHEMA_VERSION:
            raise ValueError(
                f"Unsupported license section schema version {version}. "
                f"Expected {LICENSE_SECTION_SCHEMA_VERSION} or lower."
            )
        return [dict(item) for item in list(payload.get("rows") or [])]

    @staticmethod
    def _mapped_identifier(source_id: int, mapping: dict[int, int], *, label: str) -> int:
        if int(source_id or 0) <= 0:
            raise ValueError(f"Missing source identifier for {label}.")
        mapped_id = mapping.get(int(source_id))
        if mapped_id is None:
            raise ValueError(
                f"Could not resolve {label} {int(source_id)} in the current import run."
            )
        return int(mapped_id)

    def _omitted_sections(self) -> list[dict[str, str]]:
        omitted = [
            {
                "section_id": "history_snapshots",
                "reason": "History snapshots are operational rollback state, not logical catalog data.",
            },
            {
                "section_id": "authenticity_and_derivative_ledgers",
                "reason": (
                    "Authenticity manifests, forensic exports, and derivative ledgers are runtime "
                    "artifacts rather than the authoritative logical catalog dataset."
                ),
            },
            {
                "section_id": "contract_template_runtime_artifacts",
                "reason": (
                    "Contract template drafts, resolved snapshots, and generated output artifacts "
                    "are not included in master transfer format v1."
                ),
            },
        ]
        if (
            self._table_row_count("WorkOwnershipInterests") > 0
            or self._table_row_count("RecordingOwnershipInterests") > 0
        ):
            omitted.append(
                {
                    "section_id": "ownership_interests",
                    "reason": (
                        "Work and recording ownership interests do not yet have a dedicated logical "
                        "transfer surface in format v1."
                    ),
                }
            )
        return omitted

    def _current_target_counts(self) -> dict[str, int]:
        table_to_label = {
            "Tracks": "tracks",
            "Parties": "parties",
            "Works": "works",
            "Contracts": "contracts",
            "RightsRecords": "rights",
            "AssetVersions": "assets",
            "Licenses": "licenses",
            "ContractTemplates": "contract_templates",
        }
        return {
            label: self._table_row_count(table_name) for table_name, label in table_to_label.items()
        }

    def _target_population_warnings(self) -> list[str]:
        counts = self._current_target_counts()
        if not any(counts.values()):
            return []
        return [
            "The current profile already contains data. Master transfer import is designed as a "
            "logical migration path and is safest when applied into a clean or migration profile."
        ]

    def _table_row_count(self, table_name: str) -> int:
        row = self.conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (str(table_name),),
        ).fetchone()
        if not row:
            return 0
        count_row = self.conn.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()
        return int(count_row[0] or 0) if count_row else 0
