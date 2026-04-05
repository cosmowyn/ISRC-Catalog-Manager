"""Storage and lifecycle service for contract template placeholder workflows."""

from __future__ import annotations

import json
import shutil
import sqlite3
import tempfile
import uuid
from pathlib import Path
from typing import Iterable

from isrc_manager.file_storage import (
    STORAGE_MODE_DATABASE,
    STORAGE_MODE_MANAGED_FILE,
    ManagedFileStorage,
    bytes_from_blob,
    coalesce_filename,
    guess_mime_type,
    infer_storage_mode,
    normalize_storage_mode,
    sha256_digest,
)

from .html_support import (
    HTMLTemplateBundle,
    HTMLTemplateBundleError,
    HTMLTemplateScanner,
    build_html_bundle_from_source_bytes,
    build_html_bundle_from_zip_bytes,
    build_html_bundle_from_zip_path,
    build_scan_diagnostics_payload,
    collect_html_bundle_from_directory,
    html_bundle_metadata,
    is_html_source_format,
    scan_diagnostic_entries,
    write_html_bundle,
)
from .ingestion import (
    ContractTemplateIngestionError,
    DOCXTemplateScanner,
    PagesTemplateAdapter,
    detect_template_source_format,
)
from .models import (
    ContractTemplateDraftPayload,
    ContractTemplateDraftRecord,
    ContractTemplateImportResult,
    ContractTemplateOutputArtifactPayload,
    ContractTemplateOutputArtifactRecord,
    ContractTemplatePayload,
    ContractTemplatePlaceholderBindingPayload,
    ContractTemplatePlaceholderBindingRecord,
    ContractTemplatePlaceholderPayload,
    ContractTemplatePlaceholderRecord,
    ContractTemplateRecord,
    ContractTemplateResolvedSnapshotPayload,
    ContractTemplateResolvedSnapshotRecord,
    ContractTemplateRevisionAssetPayload,
    ContractTemplateRevisionAssetRecord,
    ContractTemplateRevisionPayload,
    ContractTemplateRevisionRecord,
    ContractTemplateScanDiagnostic,
    ContractTemplateScanResult,
)
from .parser import parse_placeholder


def _clean_text(value: object | None) -> str | None:
    clean = str(value or "").strip()
    return clean or None


def _json_dumps(value: object | None) -> str | None:
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=True, separators=(",", ":"), sort_keys=True)


def _json_loads(value: object | None) -> object | None:
    text = str(value or "").strip()
    if not text:
        return None
    return json.loads(text)


def _display_label_from_key(key: str) -> str:
    return " ".join(part.capitalize() for part in str(key or "").split("_") if part)


def _html_bundle_metadata_payload(
    *,
    bundle_root: str,
    primary_relative_path: str,
    import_kind: str,
    package_filename: str | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "bundle_root": str(bundle_root),
        "primary_relative_path": str(primary_relative_path),
        "import_kind": str(import_kind),
    }
    clean_package_filename = _clean_text(package_filename)
    if clean_package_filename:
        payload["package_filename"] = clean_package_filename
    return payload


def _merged_scan_diagnostics_payload(
    diagnostics: object | None,
    *,
    html_bundle: dict[str, object] | None = None,
) -> object | None:
    return build_scan_diagnostics_payload(
        scan_diagnostic_entries(diagnostics),
        html_bundle=html_bundle,
    )


class ContractTemplateService:
    """Owns template/revision/draft records for placeholder-driven documents."""

    TEMPLATE_SOURCE_ROOT = "contract_template_sources"
    DRAFT_ROOT = "contract_template_drafts"
    ARTIFACT_ROOT = "contract_template_artifacts"

    def __init__(
        self,
        conn: sqlite3.Connection,
        data_root: str | Path | None = None,
        *,
        docx_scanner: DOCXTemplateScanner | None = None,
        html_scanner: HTMLTemplateScanner | None = None,
        pages_adapter: PagesTemplateAdapter | None = None,
    ):
        self.conn = conn
        self.data_root = Path(data_root).resolve() if data_root is not None else None
        self.source_store = ManagedFileStorage(
            data_root=self.data_root, relative_root=self.TEMPLATE_SOURCE_ROOT
        )
        self.draft_store = ManagedFileStorage(
            data_root=self.data_root, relative_root=self.DRAFT_ROOT
        )
        self.artifact_store = ManagedFileStorage(
            data_root=self.data_root, relative_root=self.ARTIFACT_ROOT
        )
        self.docx_scanner = docx_scanner if docx_scanner is not None else DOCXTemplateScanner()
        self.html_scanner = html_scanner if html_scanner is not None else HTMLTemplateScanner()
        self.pages_adapter = pages_adapter if pages_adapter is not None else PagesTemplateAdapter()

    def create_template(self, payload: ContractTemplatePayload) -> ContractTemplateRecord:
        with self.conn:
            cur = self.conn.cursor()
            cur.execute(
                """
                INSERT INTO ContractTemplates (
                    name,
                    description,
                    template_family,
                    source_format,
                    active_revision_id,
                    archived
                )
                VALUES (?, ?, ?, ?, NULL, 0)
                """,
                (
                    str(payload.name or "").strip(),
                    _clean_text(payload.description),
                    str(payload.template_family or "contract").strip() or "contract",
                    _clean_text(payload.source_format),
                ),
            )
            template_id = int(cur.lastrowid)
        record = self.fetch_template(template_id)
        if record is None:
            raise RuntimeError(f"Contract template {template_id} was not created")
        return record

    def fetch_template(self, template_id: int) -> ContractTemplateRecord | None:
        row = self.conn.execute(
            """
            SELECT
                id,
                name,
                description,
                template_family,
                source_format,
                active_revision_id,
                archived,
                created_at,
                updated_at
            FROM ContractTemplates
            WHERE id=?
            """,
            (int(template_id),),
        ).fetchone()
        if not row:
            return None
        return ContractTemplateRecord(
            template_id=int(row[0]),
            name=str(row[1] or ""),
            description=_clean_text(row[2]),
            template_family=str(row[3] or "contract"),
            source_format=_clean_text(row[4]),
            active_revision_id=int(row[5]) if row[5] is not None else None,
            archived=bool(row[6]),
            created_at=_clean_text(row[7]),
            updated_at=_clean_text(row[8]),
        )

    def list_templates(self, *, include_archived: bool = False) -> list[ContractTemplateRecord]:
        where_sql = "" if include_archived else "WHERE archived=0"
        rows = self.conn.execute(
            f"""
            SELECT
                id,
                name,
                description,
                template_family,
                source_format,
                active_revision_id,
                archived,
                created_at,
                updated_at
            FROM ContractTemplates
            {where_sql}
            ORDER BY archived ASC, updated_at DESC, id DESC
            """
        ).fetchall()
        return [
            ContractTemplateRecord(
                template_id=int(row[0]),
                name=str(row[1] or ""),
                description=_clean_text(row[2]),
                template_family=str(row[3] or "contract"),
                source_format=_clean_text(row[4]),
                active_revision_id=int(row[5]) if row[5] is not None else None,
                archived=bool(row[6]),
                created_at=_clean_text(row[7]),
                updated_at=_clean_text(row[8]),
            )
            for row in rows
        ]

    def archive_template(
        self, template_id: int, *, archived: bool = True
    ) -> ContractTemplateRecord:
        with self.conn:
            self.conn.execute(
                """
                UPDATE ContractTemplates
                SET archived=?,
                    updated_at=datetime('now')
                WHERE id=?
                """,
                (1 if archived else 0, int(template_id)),
            )
        record = self.fetch_template(template_id)
        if record is None:
            raise ValueError(f"Contract template {template_id} not found")
        return record

    def duplicate_template(
        self,
        template_id: int,
        *,
        new_name: str | None = None,
    ) -> ContractTemplateRecord:
        template = self.fetch_template(template_id)
        if template is None:
            raise ValueError(f"Contract template {template_id} not found")
        duplicate = self.create_template(
            ContractTemplatePayload(
                name=_clean_text(new_name) or f"{template.name} Copy",
                description=template.description,
                template_family=template.template_family,
                source_format=template.source_format,
            )
        )
        active_old_id = (
            int(template.active_revision_id) if template.active_revision_id is not None else None
        )
        active_new_id: int | None = None
        for revision in reversed(self.list_revisions(template_id)):
            html_bundle = None
            if is_html_source_format(revision.source_format):
                bundle_info = html_bundle_metadata(revision.scan_diagnostics) or {}
                bundle_root = self.source_store.resolve(_clean_text(bundle_info.get("bundle_root")))
                primary_relative_path = (
                    _clean_text(bundle_info.get("primary_relative_path"))
                    or revision.source_filename
                )
                if bundle_root is not None and bundle_root.exists():
                    html_bundle = collect_html_bundle_from_directory(
                        bundle_root,
                        primary_relative_path=primary_relative_path,
                    )
            copied = self.add_revision_from_bytes(
                duplicate.template_id,
                self.load_revision_source_bytes(revision.revision_id),
                payload=ContractTemplateRevisionPayload(
                    revision_label=revision.revision_label,
                    source_filename=revision.source_filename,
                    source_mime_type=revision.source_mime_type,
                    source_format=revision.source_format,
                    source_path=revision.source_path,
                    storage_mode=revision.storage_mode,
                    scan_status=revision.scan_status,
                    scan_error=revision.scan_error,
                    scan_adapter=revision.scan_adapter,
                    scan_diagnostics=scan_diagnostic_entries(revision.scan_diagnostics),
                ),
                placeholders=(
                    self._placeholder_payload_from_record(item)
                    for item in self.list_placeholders(revision.revision_id)
                ),
                bindings=(
                    self._binding_payload_from_record(item)
                    for item in self.list_placeholder_bindings(revision.revision_id)
                ),
                activate_template=False,
                html_bundle=html_bundle,
            )
            if active_old_id is not None and int(revision.revision_id) == active_old_id:
                active_new_id = copied.revision_id
        if active_new_id is not None:
            self.set_active_revision(active_new_id)
        if template.archived:
            self.archive_template(duplicate.template_id, archived=True)
        duplicated = self.fetch_template(duplicate.template_id)
        if duplicated is None:
            raise RuntimeError(f"Duplicated contract template {duplicate.template_id} disappeared")
        return duplicated

    def add_revision_from_path(
        self,
        template_id: int,
        source_path: str | Path,
        *,
        payload: ContractTemplateRevisionPayload | None = None,
        placeholders: Iterable[ContractTemplatePlaceholderPayload] = (),
        bindings: Iterable[ContractTemplatePlaceholderBindingPayload] = (),
        activate_template: bool = True,
    ) -> ContractTemplateRevisionRecord:
        source = Path(str(source_path or "").strip())
        if not source.exists():
            raise FileNotFoundError(source)
        revision_payload = payload or ContractTemplateRevisionPayload()
        source_format = detect_template_source_format(
            source_filename=source.name,
            explicit_format=revision_payload.source_format,
        )
        effective_payload = ContractTemplateRevisionPayload(
            revision_label=revision_payload.revision_label,
            source_filename=revision_payload.source_filename or source.name,
            source_mime_type=revision_payload.source_mime_type,
            source_format=source_format,
            source_path=str(source),
            source_root_path=revision_payload.source_root_path,
            source_tree_mode=revision_payload.source_tree_mode,
            storage_mode=revision_payload.storage_mode,
            scan_status=revision_payload.scan_status,
            scan_error=revision_payload.scan_error,
            scan_adapter=revision_payload.scan_adapter,
            scan_diagnostics=revision_payload.scan_diagnostics,
        )
        source_bytes = source.read_bytes()
        return self.add_revision_from_bytes(
            template_id,
            source_bytes,
            payload=effective_payload,
            placeholders=placeholders,
            bindings=bindings,
            activate_template=activate_template,
            html_bundle=(
                collect_html_bundle_from_directory(
                    (
                        Path(effective_payload.source_root_path).resolve()
                        if effective_payload.source_root_path
                        else source.parent.resolve()
                    ),
                    primary_relative_path=(
                        source.resolve()
                        .relative_to(
                            Path(effective_payload.source_root_path).resolve()
                            if effective_payload.source_root_path
                            else source.parent.resolve()
                        )
                        .as_posix()
                        if (
                            effective_payload.source_root_path
                            and source.resolve().is_relative_to(
                                Path(effective_payload.source_root_path).resolve()
                            )
                        )
                        else source.name
                    ),
                )
                if is_html_source_format(source_format)
                else None
            ),
        )

    def add_revision_from_bytes(
        self,
        template_id: int,
        source_bytes: bytes,
        *,
        payload: ContractTemplateRevisionPayload | None = None,
        placeholders: Iterable[ContractTemplatePlaceholderPayload] = (),
        bindings: Iterable[ContractTemplatePlaceholderBindingPayload] = (),
        activate_template: bool = True,
        html_bundle: HTMLTemplateBundle | None = None,
    ) -> ContractTemplateRevisionRecord:
        template = self.fetch_template(template_id)
        if template is None:
            raise ValueError(f"Contract template {template_id} not found")
        revision_payload = payload or ContractTemplateRevisionPayload()
        source_format = str(revision_payload.source_format or "docx").strip().lower() or "docx"
        clean_mode = normalize_storage_mode(
            revision_payload.storage_mode,
            default=(
                STORAGE_MODE_MANAGED_FILE if source_format == "html" else STORAGE_MODE_DATABASE
            ),
        )
        clean_filename = coalesce_filename(
            revision_payload.source_filename,
            default_stem="contract-template",
        )
        clean_mime = _clean_text(revision_payload.source_mime_type) or guess_mime_type(
            clean_filename
        )
        checksum = sha256_digest(source_bytes)
        managed_file_path = None
        sqlite_blob: bytes | sqlite3.Binary | None = None
        scan_diagnostics = revision_payload.scan_diagnostics
        if source_format == "html":
            clean_mode = STORAGE_MODE_MANAGED_FILE
            bundle = html_bundle or build_html_bundle_from_source_bytes(
                source_bytes,
                source_filename=clean_filename,
            )
            managed_file_path, bundle_root = write_html_bundle(
                self.source_store,
                bundle,
                bundle_subdir=f"html_revision_{uuid.uuid4().hex[:12]}",
            )
            scan_diagnostics = _merged_scan_diagnostics_payload(
                revision_payload.scan_diagnostics,
                html_bundle=_html_bundle_metadata_payload(
                    bundle_root=bundle_root,
                    primary_relative_path=bundle.primary_relative_path,
                    import_kind=bundle.import_kind,
                    package_filename=bundle.package_filename,
                ),
            )
        elif clean_mode == STORAGE_MODE_DATABASE:
            sqlite_blob = sqlite3.Binary(source_bytes)
        else:
            managed_file_path = self.source_store.write_bytes(source_bytes, filename=clean_filename)
        with self.conn:
            cur = self.conn.cursor()
            cur.execute(
                """
                INSERT INTO ContractTemplateRevisions (
                    template_id,
                    revision_label,
                    source_filename,
                    source_mime_type,
                    source_format,
                    source_path,
                    managed_file_path,
                    storage_mode,
                    source_blob,
                    source_checksum_sha256,
                    size_bytes,
                    scan_status,
                    scan_error,
                    scan_adapter,
                    scan_diagnostics_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    int(template_id),
                    _clean_text(revision_payload.revision_label),
                    clean_filename,
                    clean_mime,
                    source_format,
                    _clean_text(revision_payload.source_path),
                    managed_file_path,
                    clean_mode,
                    sqlite_blob,
                    checksum,
                    len(source_bytes),
                    str(revision_payload.scan_status or "scan_pending").strip() or "scan_pending",
                    _clean_text(revision_payload.scan_error),
                    _clean_text(revision_payload.scan_adapter),
                    _json_dumps(scan_diagnostics),
                ),
            )
            revision_id = int(cur.lastrowid)
            inventory_count, inventory_hash, effective_scan_status, effective_scan_error = (
                self._replace_revision_placeholder_inventory(
                    revision_id,
                    placeholders=placeholders,
                    bindings=bindings,
                    cursor=cur,
                    scan_status=revision_payload.scan_status,
                    scan_error=revision_payload.scan_error,
                )
            )
            cur.execute(
                """
                UPDATE ContractTemplateRevisions
                SET placeholder_count=?,
                    placeholder_inventory_hash=?,
                    scan_status=?,
                    scan_error=?,
                    scan_adapter=?,
                    scan_diagnostics_json=?,
                    updated_at=datetime('now')
                WHERE id=?
                """,
                (
                    inventory_count,
                    inventory_hash,
                    effective_scan_status,
                    effective_scan_error,
                    _clean_text(revision_payload.scan_adapter),
                    _json_dumps(scan_diagnostics),
                    revision_id,
                ),
            )
            if activate_template:
                self._set_template_active_revision(
                    int(template_id),
                    revision_id,
                    str(revision_payload.source_format or "docx").strip() or "docx",
                    cursor=cur,
                )
            else:
                cur.execute(
                    """
                    UPDATE ContractTemplates
                    SET source_format=?,
                        updated_at=datetime('now')
                    WHERE id=?
                    """,
                    (
                        source_format,
                        int(template_id),
                    ),
                )
        record = self.fetch_revision(revision_id)
        if record is None:
            raise RuntimeError(f"Contract template revision {revision_id} was not created")
        if is_html_source_format(source_format) and managed_file_path:
            self.replace_revision_assets(
                revision_id,
                assets=self._html_asset_payloads_for_source(managed_file_path),
            )
        return record

    def fetch_revision(self, revision_id: int) -> ContractTemplateRevisionRecord | None:
        row = self.conn.execute(
            """
            SELECT
                id,
                template_id,
                revision_label,
                source_filename,
                source_mime_type,
                source_format,
                source_path,
                managed_file_path,
                storage_mode,
                source_checksum_sha256,
                size_bytes,
                scan_status,
                scan_error,
                scan_adapter,
                scan_diagnostics_json,
                placeholder_inventory_hash,
                placeholder_count,
                created_at,
                updated_at,
                CASE WHEN source_blob IS NOT NULL THEN 1 ELSE 0 END AS has_blob
            FROM ContractTemplateRevisions
            WHERE id=?
            """,
            (int(revision_id),),
        ).fetchone()
        if not row:
            return None
        mode = infer_storage_mode(
            explicit_mode=row[8],
            stored_path=row[7],
            blob_value=b"x" if row[19] else None,
            default=STORAGE_MODE_DATABASE,
        )
        return ContractTemplateRevisionRecord(
            revision_id=int(row[0]),
            template_id=int(row[1]),
            revision_label=_clean_text(row[2]),
            source_filename=str(row[3] or ""),
            source_mime_type=_clean_text(row[4]),
            source_format=str(row[5] or "docx"),
            source_path=_clean_text(row[6]),
            managed_file_path=_clean_text(row[7]),
            storage_mode=mode,
            source_checksum_sha256=_clean_text(row[9]),
            size_bytes=int(row[10] or 0),
            scan_status=str(row[11] or "scan_pending"),
            scan_error=_clean_text(row[12]),
            scan_adapter=_clean_text(row[13]),
            scan_diagnostics=_json_loads(row[14]),
            placeholder_inventory_hash=_clean_text(row[15]),
            placeholder_count=int(row[16] or 0),
            created_at=_clean_text(row[17]),
            updated_at=_clean_text(row[18]),
            stored_in_database=(mode == STORAGE_MODE_DATABASE),
        )

    def list_revisions(self, template_id: int) -> list[ContractTemplateRevisionRecord]:
        rows = self.conn.execute(
            """
            SELECT id
            FROM ContractTemplateRevisions
            WHERE template_id=?
            ORDER BY id DESC
            """,
            (int(template_id),),
        ).fetchall()
        records: list[ContractTemplateRevisionRecord] = []
        for row in rows:
            record = self.fetch_revision(int(row[0]))
            if record is not None:
                records.append(record)
        return records

    def list_revision_assets(self, revision_id: int) -> list[ContractTemplateRevisionAssetRecord]:
        rows = self.conn.execute(
            """
            SELECT
                id,
                revision_id,
                package_rel_path,
                managed_file_path,
                source_filename,
                mime_type,
                size_bytes,
                checksum_sha256,
                asset_role,
                created_at
            FROM ContractTemplateRevisionAssets
            WHERE revision_id=?
            ORDER BY package_rel_path ASC, id ASC
            """,
            (int(revision_id),),
        ).fetchall()
        return [
            ContractTemplateRevisionAssetRecord(
                asset_id=int(row[0]),
                revision_id=int(row[1]),
                package_rel_path=str(row[2] or ""),
                managed_file_path=str(row[3] or ""),
                source_filename=str(row[4] or ""),
                mime_type=_clean_text(row[5]),
                size_bytes=int(row[6] or 0),
                checksum_sha256=_clean_text(row[7]),
                asset_role=str(row[8] or "asset"),
                created_at=_clean_text(row[9]),
            )
            for row in rows
        ]

    def replace_revision_assets(
        self,
        revision_id: int,
        *,
        assets: Iterable[ContractTemplateRevisionAssetPayload],
    ) -> list[ContractTemplateRevisionAssetRecord]:
        revision = self.fetch_revision(revision_id)
        if revision is None:
            raise ValueError(f"Contract template revision {revision_id} not found")
        with self.conn:
            cur = self.conn.cursor()
            cur.execute(
                "DELETE FROM ContractTemplateRevisionAssets WHERE revision_id=?",
                (int(revision_id),),
            )
            for asset in assets:
                clean_package_rel_path = str(asset.package_rel_path or "").strip()
                clean_managed_file_path = str(asset.managed_file_path or "").strip()
                if not clean_package_rel_path or not clean_managed_file_path:
                    continue
                cur.execute(
                    """
                    INSERT INTO ContractTemplateRevisionAssets (
                        revision_id,
                        package_rel_path,
                        managed_file_path,
                        source_filename,
                        mime_type,
                        size_bytes,
                        checksum_sha256,
                        asset_role
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        int(revision_id),
                        clean_package_rel_path,
                        clean_managed_file_path,
                        coalesce_filename(
                            asset.source_filename,
                            stored_path=clean_package_rel_path,
                            default_stem=Path(clean_package_rel_path).stem or "asset",
                        ),
                        _clean_text(asset.mime_type) or guess_mime_type(clean_package_rel_path),
                        max(0, int(asset.size_bytes or 0)),
                        _clean_text(asset.checksum_sha256),
                        _clean_text(asset.asset_role) or "asset",
                    ),
                )
        return self.list_revision_assets(revision_id)

    def set_active_revision(self, revision_id: int) -> ContractTemplateRecord:
        record = self.fetch_revision(revision_id)
        if record is None:
            raise ValueError(f"Contract template revision {revision_id} not found")
        with self.conn:
            self._set_template_active_revision(
                record.template_id,
                record.revision_id,
                record.source_format,
                cursor=self.conn.cursor(),
            )
        template = self.fetch_template(record.template_id)
        if template is None:
            raise RuntimeError(
                f"Contract template {record.template_id} disappeared after activation"
            )
        return template

    def scan_source_bytes(
        self,
        source_bytes: bytes,
        *,
        source_filename: str | None = None,
        source_format: str | None = None,
    ) -> ContractTemplateScanResult:
        resolved_format = detect_template_source_format(
            source_filename=source_filename,
            explicit_format=source_format,
        )
        return self._scan_source_bytes(
            source_bytes,
            source_filename=source_filename,
            source_format=resolved_format,
        )

    def scan_source_path(
        self,
        source_path: str | Path,
        *,
        source_filename: str | None = None,
        source_format: str | None = None,
    ) -> ContractTemplateScanResult:
        source = Path(str(source_path or "").strip())
        if not source.exists():
            raise FileNotFoundError(source)
        effective_filename = source_filename or source.name
        resolved_format = detect_template_source_format(
            source_filename=effective_filename,
            explicit_format=source_format,
        )
        if source.suffix.lower() == ".zip" and resolved_format == "html":
            try:
                bundle = build_html_bundle_from_zip_path(source)
            except HTMLTemplateBundleError as exc:
                raise ContractTemplateIngestionError(str(exc)) from exc
            return self._scan_source_bytes(
                bundle.primary_bytes(),
                source_filename=bundle.primary_filename,
                source_format=resolved_format,
            )
        return self._scan_source_bytes(
            source.read_bytes(),
            source_filename=effective_filename,
            source_format=resolved_format,
        )

    def import_revision_from_path(
        self,
        template_id: int,
        source_path: str | Path,
        *,
        payload: ContractTemplateRevisionPayload | None = None,
        bindings: Iterable[ContractTemplatePlaceholderBindingPayload] = (),
        activate_if_ready: bool = True,
    ) -> ContractTemplateImportResult:
        source = Path(str(source_path or "").strip())
        if not source.exists():
            raise FileNotFoundError(source)
        explicit_source_format = payload.source_format if payload is not None else None
        if source.suffix.lower() == ".zip" and str(
            explicit_source_format or ""
        ).strip().lower() in {
            "",
            "html",
        }:
            return self.import_html_package_from_path(
                template_id,
                source,
                payload=payload,
                bindings=bindings,
                activate_if_ready=activate_if_ready,
            )
        scan_result = self.scan_source_path(
            source,
            source_filename=source.name,
            source_format=explicit_source_format,
        )
        revision_payload = self._revision_payload_for_import(
            source_filename=source.name,
            source_format=detect_template_source_format(
                source_filename=source.name,
                explicit_format=explicit_source_format,
            ),
            payload=payload,
            scan_result=scan_result,
            source_path=source,
        )
        revision = self.add_revision_from_path(
            template_id,
            source,
            payload=revision_payload,
            placeholders=self._placeholder_payloads_from_scan_result(scan_result),
            bindings=bindings,
            activate_template=False,
        )
        if activate_if_ready and scan_result.scan_status == "scan_ready":
            self.set_active_revision(revision.revision_id)
            revision = self.fetch_revision(revision.revision_id) or revision
        return ContractTemplateImportResult(revision=revision, scan_result=scan_result)

    def import_revision_from_bytes(
        self,
        template_id: int,
        source_bytes: bytes,
        *,
        payload: ContractTemplateRevisionPayload | None = None,
        bindings: Iterable[ContractTemplatePlaceholderBindingPayload] = (),
        activate_if_ready: bool = True,
    ) -> ContractTemplateImportResult:
        explicit_source_format = payload.source_format if payload is not None else None
        source_filename = (payload.source_filename if payload is not None else None) or (
            "contract-template.html"
            if explicit_source_format == "html"
            else (
                "contract-template.pages"
                if explicit_source_format == "pages"
                else "contract-template.docx"
            )
        )
        if Path(source_filename).suffix.lower() == ".zip" and str(
            explicit_source_format or ""
        ).strip().lower() in {"", "html"}:
            try:
                bundle = build_html_bundle_from_zip_bytes(
                    source_bytes,
                    package_filename=source_filename,
                )
            except HTMLTemplateBundleError as exc:
                raise ContractTemplateIngestionError(str(exc)) from exc
            return self._import_html_bundle_from_bundle(
                template_id,
                bundle,
                payload=payload,
                bindings=bindings,
                activate_if_ready=activate_if_ready,
            )
        scan_result = self.scan_source_bytes(
            source_bytes,
            source_filename=source_filename,
            source_format=explicit_source_format,
        )
        revision_payload = self._revision_payload_for_import(
            source_filename=source_filename,
            source_format=detect_template_source_format(
                source_filename=source_filename,
                explicit_format=explicit_source_format,
            ),
            payload=payload,
            scan_result=scan_result,
            source_path=(
                Path(str(payload.source_path).strip()) if payload and payload.source_path else None
            ),
        )
        revision = self.add_revision_from_bytes(
            template_id,
            source_bytes,
            payload=revision_payload,
            placeholders=self._placeholder_payloads_from_scan_result(scan_result),
            bindings=bindings,
            activate_template=False,
        )
        if activate_if_ready and scan_result.scan_status == "scan_ready":
            self.set_active_revision(revision.revision_id)
            revision = self.fetch_revision(revision.revision_id) or revision
        return ContractTemplateImportResult(revision=revision, scan_result=scan_result)

    def rescan_revision(
        self,
        revision_id: int,
        *,
        preserve_bindings: bool = True,
        activate_if_ready: bool = False,
    ) -> ContractTemplateScanResult:
        record = self.fetch_revision(revision_id)
        if record is None:
            raise ValueError(f"Contract template revision {revision_id} not found")
        bundle_info = (
            html_bundle_metadata(record.scan_diagnostics)
            if is_html_source_format(record.source_format)
            else None
        )
        scan_result = self.scan_source_bytes(
            self.load_revision_source_bytes(revision_id),
            source_filename=record.source_filename,
            source_format=record.source_format,
        )
        scan_diagnostics_payload = _merged_scan_diagnostics_payload(
            [item.to_dict() for item in scan_result.diagnostics],
            html_bundle=bundle_info,
        )
        if scan_result.scan_status == "scan_ready":
            bindings = (
                self._preserved_binding_payloads(revision_id, scan_result)
                if preserve_bindings
                else ()
            )
            self.replace_revision_placeholder_inventory(
                revision_id,
                placeholders=self._placeholder_payloads_from_scan_result(scan_result),
                bindings=bindings,
                scan_status=scan_result.scan_status,
                scan_error=self._scan_error_summary(scan_result),
                scan_adapter=scan_result.scan_adapter,
                scan_diagnostics=scan_diagnostics_payload,
            )
            if activate_if_ready:
                self.set_active_revision(revision_id)
        else:
            self._update_revision_scan_state(
                revision_id,
                scan_status=scan_result.scan_status,
                scan_error=self._scan_error_summary(scan_result),
                scan_adapter=scan_result.scan_adapter,
                scan_diagnostics=scan_diagnostics_payload,
            )
        return scan_result

    def import_html_package_from_path(
        self,
        template_id: int,
        package_path: str | Path,
        *,
        payload: ContractTemplateRevisionPayload | None = None,
        bindings: Iterable[ContractTemplatePlaceholderBindingPayload] = (),
        activate_if_ready: bool = True,
    ) -> ContractTemplateImportResult:
        package = Path(str(package_path or "").strip())
        if not package.exists():
            raise FileNotFoundError(package)
        try:
            bundle = build_html_bundle_from_zip_path(package)
        except HTMLTemplateBundleError as exc:
            raise ContractTemplateIngestionError(str(exc)) from exc
        return self._import_html_bundle_from_bundle(
            template_id,
            bundle,
            payload=payload,
            bindings=bindings,
            activate_if_ready=activate_if_ready,
            source_path=str(package),
        )

    def _import_html_bundle_from_bundle(
        self,
        template_id: int,
        bundle: HTMLTemplateBundle,
        *,
        payload: ContractTemplateRevisionPayload | None = None,
        bindings: Iterable[ContractTemplatePlaceholderBindingPayload] = (),
        activate_if_ready: bool = True,
        source_path: str | None = None,
    ) -> ContractTemplateImportResult:
        scan_result = self.scan_source_bytes(
            bundle.primary_bytes(),
            source_filename=bundle.primary_filename,
            source_format="html",
        )
        import_payload = payload or ContractTemplateRevisionPayload()
        revision = self.add_revision_from_bytes(
            template_id,
            bundle.primary_bytes(),
            payload=ContractTemplateRevisionPayload(
                revision_label=import_payload.revision_label,
                source_filename=import_payload.source_filename or bundle.primary_filename,
                source_mime_type=(
                    import_payload.source_mime_type or guess_mime_type(bundle.primary_filename)
                ),
                source_format="html",
                source_path=_clean_text(source_path) or import_payload.source_path,
                storage_mode=STORAGE_MODE_MANAGED_FILE,
                scan_status=scan_result.scan_status,
                scan_error=self._scan_error_summary(scan_result),
                scan_adapter=scan_result.scan_adapter,
                scan_diagnostics=scan_diagnostic_entries(import_payload.scan_diagnostics),
            ),
            placeholders=self._placeholder_payloads_from_scan_result(scan_result),
            bindings=bindings,
            activate_template=False,
            html_bundle=bundle,
        )
        if activate_if_ready and scan_result.scan_status == "scan_ready":
            self.set_active_revision(revision.revision_id)
            revision = self.fetch_revision(revision.revision_id) or revision
        return ContractTemplateImportResult(revision=revision, scan_result=scan_result)

    def _set_template_active_revision(
        self,
        template_id: int,
        revision_id: int,
        source_format: str,
        *,
        cursor: sqlite3.Cursor,
    ) -> None:
        cursor.execute(
            """
            UPDATE ContractTemplates
            SET active_revision_id=?,
                source_format=?,
                updated_at=datetime('now')
            WHERE id=?
            """,
            (
                int(revision_id),
                str(source_format or "docx").strip() or "docx",
                int(template_id),
            ),
        )

    def _revision_payload_for_import(
        self,
        *,
        source_filename: str,
        source_format: str,
        payload: ContractTemplateRevisionPayload | None,
        scan_result: ContractTemplateScanResult,
        source_path: Path | None,
    ) -> ContractTemplateRevisionPayload:
        base = payload or ContractTemplateRevisionPayload()
        return ContractTemplateRevisionPayload(
            revision_label=base.revision_label,
            source_filename=base.source_filename or source_filename,
            source_mime_type=base.source_mime_type,
            source_format=source_format,
            source_path=str(source_path) if source_path is not None else base.source_path,
            source_root_path=(
                base.source_root_path
                if base.source_root_path is not None
                else (str(source_path.parent) if source_format == "html" and source_path else None)
            ),
            source_tree_mode=base.source_tree_mode
            or ("asset_refs" if source_format == "html" else None),
            storage_mode=base.storage_mode,
            scan_status=scan_result.scan_status,
            scan_error=self._scan_error_summary(scan_result),
            scan_adapter=scan_result.scan_adapter,
            scan_diagnostics=[item.to_dict() for item in scan_result.diagnostics],
        )

    def _scan_source_bytes(
        self,
        source_bytes: bytes,
        *,
        source_filename: str | None,
        source_format: str,
    ) -> ContractTemplateScanResult:
        if source_format == "docx":
            return self.docx_scanner.scan_bytes(source_bytes)
        if source_format == "html":
            return self.html_scanner.scan_bytes(source_bytes, source_filename=source_filename)
        if source_format == "pages":
            return self._scan_pages_bytes(source_bytes, source_filename=source_filename)
        raise ContractTemplateIngestionError(f"Unsupported template source format: {source_format}")

    def _scan_pages_bytes(
        self,
        source_bytes: bytes,
        *,
        source_filename: str | None,
    ) -> ContractTemplateScanResult:
        if not self.pages_adapter.is_available():
            return ContractTemplateScanResult(
                source_format="pages",
                scan_format="docx",
                scan_status="scan_blocked",
                scan_adapter=self.pages_adapter.adapter_name,
                placeholders=(),
                diagnostics=(
                    ContractTemplateScanDiagnostic(
                        severity="error",
                        code="pages_bridge_unavailable",
                        message=self.pages_adapter.availability_message()
                        or "Pages conversion is unavailable on this machine.",
                    ),
                ),
            )
        with tempfile.TemporaryDirectory(prefix="contract-template-pages-") as tmpdir:
            workdir = Path(tmpdir)
            staged_name = coalesce_filename(
                source_filename,
                default_stem="contract-template",
                default_suffix=".pages",
            )
            source_path = workdir / staged_name
            if source_path.suffix.lower() != ".pages":
                source_path = source_path.with_suffix(".pages")
            source_path.write_bytes(source_bytes)
            converted_path = workdir / f"{source_path.stem}.docx"
            try:
                self.pages_adapter.convert_to_docx(source_path, converted_path)
            except ContractTemplateIngestionError as exc:
                return ContractTemplateScanResult(
                    source_format="pages",
                    scan_format="docx",
                    scan_status="scan_blocked",
                    scan_adapter=self.pages_adapter.adapter_name,
                    placeholders=(),
                    diagnostics=(
                        ContractTemplateScanDiagnostic(
                            severity="error",
                            code="pages_conversion_failed",
                            message=str(exc),
                            source_part=source_path.name,
                        ),
                    ),
                )
            docx_result = self.docx_scanner.scan_bytes(converted_path.read_bytes())
        return ContractTemplateScanResult(
            source_format="pages",
            scan_format=docx_result.scan_format,
            scan_status=docx_result.scan_status,
            scan_adapter=self.pages_adapter.adapter_name,
            placeholders=docx_result.placeholders,
            diagnostics=docx_result.diagnostics,
        )

    def _scan_error_summary(self, scan_result: ContractTemplateScanResult) -> str | None:
        for item in scan_result.diagnostics:
            if str(item.severity or "").strip().lower() == "error":
                return _clean_text(item.message)
        return None

    def _placeholder_payloads_from_scan_result(
        self, scan_result: ContractTemplateScanResult
    ) -> tuple[ContractTemplatePlaceholderPayload, ...]:
        return tuple(
            ContractTemplatePlaceholderPayload(
                canonical_symbol=item.canonical_symbol,
                source_occurrence_count=max(1, int(item.occurrence_count or 1)),
                metadata={"occurrences": [occurrence.to_dict() for occurrence in item.occurrences]},
            )
            for item in scan_result.placeholders
        )

    def _preserved_binding_payloads(
        self, revision_id: int, scan_result: ContractTemplateScanResult
    ) -> tuple[ContractTemplatePlaceholderBindingPayload, ...]:
        allowed_symbols = {item.canonical_symbol for item in scan_result.placeholders}
        return tuple(
            ContractTemplatePlaceholderBindingPayload(
                canonical_symbol=item.canonical_symbol,
                resolver_kind=item.resolver_kind,
                resolver_target=item.resolver_target,
                scope_entity_type=item.scope_entity_type,
                scope_policy=item.scope_policy,
                widget_hint=item.widget_hint,
                validation=item.validation,
                metadata=item.metadata,
            )
            for item in self.list_placeholder_bindings(revision_id)
            if item.canonical_symbol in allowed_symbols
        )

    def _update_revision_scan_state(
        self,
        revision_id: int,
        *,
        scan_status: str,
        scan_error: str | None,
        scan_adapter: str | None,
        scan_diagnostics: object | None,
    ) -> None:
        with self.conn:
            self.conn.execute(
                """
                UPDATE ContractTemplateRevisions
                SET scan_status=?,
                    scan_error=?,
                    scan_adapter=?,
                    scan_diagnostics_json=?,
                    updated_at=datetime('now')
                WHERE id=?
                """,
                (
                    str(scan_status or "scan_pending").strip() or "scan_pending",
                    _clean_text(scan_error),
                    _clean_text(scan_adapter),
                    _json_dumps(scan_diagnostics),
                    int(revision_id),
                ),
            )

    def load_revision_source_bytes(self, revision_id: int) -> bytes:
        row = self.conn.execute(
            """
            SELECT source_blob, managed_file_path, storage_mode, source_filename
            FROM ContractTemplateRevisions
            WHERE id=?
            """,
            (int(revision_id),),
        ).fetchone()
        if not row:
            raise FileNotFoundError(revision_id)
        blob_value, managed_file_path, storage_mode, source_filename = row
        mode = infer_storage_mode(
            explicit_mode=storage_mode,
            stored_path=managed_file_path,
            blob_value=blob_value,
            default=STORAGE_MODE_DATABASE,
        )
        if mode == STORAGE_MODE_DATABASE:
            if blob_value is None:
                raise FileNotFoundError(source_filename or revision_id)
            return bytes_from_blob(blob_value)
        resolved = self.source_store.resolve(managed_file_path)
        if resolved is None or not resolved.exists():
            raise FileNotFoundError(str(managed_file_path or source_filename or revision_id))
        return resolved.read_bytes()

    def resolve_html_revision_source_path(self, revision_id: int) -> Path | None:
        revision = self.fetch_revision(revision_id)
        if revision is None or str(revision.source_format or "").strip().lower() != "html":
            return None
        bundle_info = html_bundle_metadata(revision.scan_diagnostics) or {}
        bundle_root = self.source_store.resolve(_clean_text(bundle_info.get("bundle_root")))
        primary_relative_path = (
            _clean_text(bundle_info.get("primary_relative_path")) or revision.source_filename
        )
        if bundle_root is not None:
            candidate = bundle_root / Path(primary_relative_path)
            if candidate.exists():
                return candidate
        resolved = self.source_store.resolve(revision.managed_file_path)
        if resolved is not None and resolved.exists():
            return resolved
        return None

    def html_package_root_for_path(self, source_path: str | Path) -> Path:
        root_path = self.source_store.root_path
        resolved = Path(source_path).resolve()
        if root_path is None:
            return resolved.parent
        try:
            relative = resolved.relative_to(root_path.resolve())
        except Exception:
            return resolved.parent
        if not relative.parts:
            return resolved.parent
        return root_path / relative.parts[0]

    def resolve_html_revision_bundle_root(self, revision_id: int) -> Path | None:
        revision = self.fetch_revision(revision_id)
        if revision is None or not is_html_source_format(revision.source_format):
            return None
        bundle_info = html_bundle_metadata(revision.scan_diagnostics) or {}
        bundle_root = self.source_store.resolve(_clean_text(bundle_info.get("bundle_root")))
        if bundle_root is not None and bundle_root.exists():
            return bundle_root
        source_path = self.source_store.resolve(revision.managed_file_path)
        if source_path is not None and source_path.exists():
            return source_path.parent
        return None

    def convert_revision_storage_mode(
        self, revision_id: int, target_mode: str
    ) -> ContractTemplateRevisionRecord:
        record = self.fetch_revision(revision_id)
        if record is None:
            raise ValueError(f"Contract template revision {revision_id} not found")
        clean_mode = normalize_storage_mode(target_mode)
        if str(record.source_format or "").strip().lower() == "html":
            if clean_mode != STORAGE_MODE_MANAGED_FILE:
                raise ValueError(
                    "HTML template revisions must stay in managed-file storage so assets remain available."
                )
            return record
        if record.storage_mode == clean_mode:
            return record
        data = self.load_revision_source_bytes(revision_id)
        stale_path = _clean_text(record.managed_file_path)
        if clean_mode == STORAGE_MODE_DATABASE:
            with self.conn:
                cur = self.conn.cursor()
                cur.execute(
                    """
                    UPDATE ContractTemplateRevisions
                    SET managed_file_path=NULL,
                        storage_mode=?,
                        source_blob=?,
                        source_checksum_sha256=?,
                        size_bytes=?,
                        updated_at=datetime('now')
                    WHERE id=?
                    """,
                    (
                        clean_mode,
                        sqlite3.Binary(data),
                        sha256_digest(data),
                        len(data),
                        int(revision_id),
                    ),
                )
                if stale_path:
                    self._delete_unreferenced_managed_file(
                        table_name="ContractTemplateRevisions",
                        path_column="managed_file_path",
                        stored_path=stale_path,
                        file_store=self.source_store,
                        cursor=cur,
                    )
        else:
            rel_path = self.source_store.write_bytes(data, filename=record.source_filename)
            resolved = self.source_store.resolve(rel_path)
            if resolved is None or not resolved.exists() or resolved.read_bytes() != data:
                raise RuntimeError("Managed template source conversion verification failed")
            with self.conn:
                cur = self.conn.cursor()
                cur.execute(
                    """
                    UPDATE ContractTemplateRevisions
                    SET managed_file_path=?,
                        storage_mode=?,
                        source_blob=NULL,
                        source_checksum_sha256=?,
                        size_bytes=?,
                        updated_at=datetime('now')
                    WHERE id=?
                    """,
                    (
                        rel_path,
                        clean_mode,
                        sha256_digest(data),
                        len(data),
                        int(revision_id),
                    ),
                )
                if stale_path and stale_path != rel_path:
                    self._delete_unreferenced_managed_file(
                        table_name="ContractTemplateRevisions",
                        path_column="managed_file_path",
                        stored_path=stale_path,
                        file_store=self.source_store,
                        cursor=cur,
                    )
        updated = self.fetch_revision(revision_id)
        if updated is None:
            raise RuntimeError(
                f"Contract template revision {revision_id} disappeared after conversion"
            )
        return updated

    def replace_revision_placeholder_inventory(
        self,
        revision_id: int,
        *,
        placeholders: Iterable[ContractTemplatePlaceholderPayload],
        bindings: Iterable[ContractTemplatePlaceholderBindingPayload] = (),
        scan_status: str | None = None,
        scan_error: str | None = None,
        scan_adapter: str | None = None,
        scan_diagnostics: object | None = None,
    ) -> ContractTemplateRevisionRecord:
        current = self.fetch_revision(revision_id)
        if current is None:
            raise ValueError(f"Contract template revision {revision_id} not found")
        with self.conn:
            cur = self.conn.cursor()
            inventory_count, inventory_hash, effective_scan_status, effective_scan_error = (
                self._replace_revision_placeholder_inventory(
                    revision_id,
                    placeholders=placeholders,
                    bindings=bindings,
                    cursor=cur,
                    scan_status=scan_status,
                    scan_error=scan_error,
                )
            )
            cur.execute(
                """
                UPDATE ContractTemplateRevisions
                SET placeholder_count=?,
                    placeholder_inventory_hash=?,
                    scan_status=?,
                    scan_error=?,
                    scan_adapter=?,
                    scan_diagnostics_json=?,
                    updated_at=datetime('now')
                WHERE id=?
                """,
                (
                    inventory_count,
                    inventory_hash,
                    effective_scan_status,
                    effective_scan_error,
                    current.scan_adapter if scan_adapter is None else _clean_text(scan_adapter),
                    _json_dumps(
                        current.scan_diagnostics if scan_diagnostics is None else scan_diagnostics
                    ),
                    int(revision_id),
                ),
            )
        record = self.fetch_revision(revision_id)
        if record is None:
            raise ValueError(f"Contract template revision {revision_id} not found")
        return record

    def _replace_revision_placeholder_inventory(
        self,
        revision_id: int,
        *,
        placeholders: Iterable[ContractTemplatePlaceholderPayload],
        bindings: Iterable[ContractTemplatePlaceholderBindingPayload],
        cursor: sqlite3.Cursor,
        scan_status: str | None,
        scan_error: str | None,
    ) -> tuple[int, str | None, str, str | None]:
        placeholder_rows = self._normalize_placeholder_payloads(placeholders)
        binding_rows = self._normalize_binding_payloads(bindings)
        missing_binding_symbols = set(binding_rows) - set(placeholder_rows)
        if missing_binding_symbols:
            missing = ", ".join(sorted(missing_binding_symbols))
            raise ValueError(f"Binding metadata references unknown placeholders: {missing}")

        cursor.execute(
            "DELETE FROM ContractTemplatePlaceholderBindings WHERE revision_id=?",
            (int(revision_id),),
        )
        cursor.execute(
            "DELETE FROM ContractTemplatePlaceholders WHERE revision_id=?",
            (int(revision_id),),
        )

        placeholder_ids: dict[str, int] = {}
        for canonical_symbol, item in placeholder_rows.items():
            token = parse_placeholder(canonical_symbol)
            cursor.execute(
                """
                INSERT INTO ContractTemplatePlaceholders (
                    revision_id,
                    canonical_symbol,
                    binding_kind,
                    namespace,
                    placeholder_key,
                    display_label,
                    inferred_field_type,
                    required,
                    source_occurrence_count,
                    metadata_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    int(revision_id),
                    token.canonical_symbol,
                    token.binding_kind,
                    token.namespace,
                    token.key,
                    item.display_label or _display_label_from_key(token.key),
                    _clean_text(item.inferred_field_type),
                    1 if item.required else 0,
                    max(1, int(item.source_occurrence_count or 1)),
                    _json_dumps(item.metadata),
                ),
            )
            placeholder_ids[token.canonical_symbol] = int(cursor.lastrowid)

        for canonical_symbol, item in binding_rows.items():
            token = parse_placeholder(canonical_symbol)
            cursor.execute(
                """
                INSERT INTO ContractTemplatePlaceholderBindings (
                    revision_id,
                    placeholder_id,
                    canonical_symbol,
                    resolver_kind,
                    resolver_target,
                    scope_entity_type,
                    scope_policy,
                    widget_hint,
                    validation_json,
                    metadata_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    int(revision_id),
                    int(placeholder_ids[token.canonical_symbol]),
                    token.canonical_symbol,
                    _clean_text(item.resolver_kind) or token.binding_kind,
                    _clean_text(item.resolver_target),
                    _clean_text(item.scope_entity_type),
                    _clean_text(item.scope_policy),
                    _clean_text(item.widget_hint),
                    _json_dumps(item.validation),
                    _json_dumps(item.metadata),
                ),
            )

        inventory_payload = [
            {
                "canonical_symbol": canonical_symbol,
                "binding_kind": parse_placeholder(canonical_symbol).binding_kind,
                "namespace": parse_placeholder(canonical_symbol).namespace,
                "key": parse_placeholder(canonical_symbol).key,
                "display_label": placeholder_rows[canonical_symbol].display_label
                or _display_label_from_key(parse_placeholder(canonical_symbol).key),
                "inferred_field_type": placeholder_rows[canonical_symbol].inferred_field_type,
                "required": bool(placeholder_rows[canonical_symbol].required),
                "source_occurrence_count": max(
                    1, int(placeholder_rows[canonical_symbol].source_occurrence_count or 1)
                ),
            }
            for canonical_symbol in sorted(placeholder_rows)
        ]
        inventory_json = _json_dumps(inventory_payload)
        inventory_hash = sha256_digest(inventory_json.encode("utf-8")) if inventory_json else None
        effective_scan_status = str(scan_status or "").strip() or (
            "scan_ready" if placeholder_rows else "scan_pending"
        )
        effective_scan_error = _clean_text(scan_error)
        if effective_scan_error:
            effective_scan_status = "scan_blocked"
        return len(placeholder_rows), inventory_hash, effective_scan_status, effective_scan_error

    def _normalize_placeholder_payloads(
        self, placeholders: Iterable[ContractTemplatePlaceholderPayload]
    ) -> dict[str, ContractTemplatePlaceholderPayload]:
        normalized: dict[str, ContractTemplatePlaceholderPayload] = {}
        for item in placeholders:
            token = parse_placeholder(item.canonical_symbol)
            current = normalized.get(token.canonical_symbol)
            if current is None:
                normalized[token.canonical_symbol] = ContractTemplatePlaceholderPayload(
                    canonical_symbol=token.canonical_symbol,
                    display_label=item.display_label,
                    inferred_field_type=item.inferred_field_type,
                    required=bool(item.required),
                    source_occurrence_count=max(1, int(item.source_occurrence_count or 1)),
                    metadata=item.metadata,
                )
                continue
            normalized[token.canonical_symbol] = ContractTemplatePlaceholderPayload(
                canonical_symbol=token.canonical_symbol,
                display_label=current.display_label or item.display_label,
                inferred_field_type=current.inferred_field_type or item.inferred_field_type,
                required=bool(current.required or item.required),
                source_occurrence_count=max(
                    1,
                    int(current.source_occurrence_count or 1)
                    + max(1, int(item.source_occurrence_count or 1)),
                ),
                metadata=current.metadata if current.metadata is not None else item.metadata,
            )
        return normalized

    def _normalize_binding_payloads(
        self, bindings: Iterable[ContractTemplatePlaceholderBindingPayload]
    ) -> dict[str, ContractTemplatePlaceholderBindingPayload]:
        normalized: dict[str, ContractTemplatePlaceholderBindingPayload] = {}
        for item in bindings:
            token = parse_placeholder(item.canonical_symbol)
            if token.canonical_symbol in normalized:
                raise ValueError(f"Duplicate binding metadata for {token.canonical_symbol}")
            normalized[token.canonical_symbol] = ContractTemplatePlaceholderBindingPayload(
                canonical_symbol=token.canonical_symbol,
                resolver_kind=item.resolver_kind,
                resolver_target=item.resolver_target,
                scope_entity_type=item.scope_entity_type,
                scope_policy=item.scope_policy,
                widget_hint=item.widget_hint,
                validation=item.validation,
                metadata=item.metadata,
            )
        return normalized

    def list_placeholders(self, revision_id: int) -> list[ContractTemplatePlaceholderRecord]:
        rows = self.conn.execute(
            """
            SELECT
                id,
                revision_id,
                canonical_symbol,
                binding_kind,
                namespace,
                placeholder_key,
                display_label,
                inferred_field_type,
                required,
                source_occurrence_count,
                metadata_json
            FROM ContractTemplatePlaceholders
            WHERE revision_id=?
            ORDER BY canonical_symbol ASC
            """,
            (int(revision_id),),
        ).fetchall()
        return [
            ContractTemplatePlaceholderRecord(
                placeholder_id=int(row[0]),
                revision_id=int(row[1]),
                canonical_symbol=str(row[2] or ""),
                binding_kind=str(row[3] or ""),
                namespace=_clean_text(row[4]),
                placeholder_key=str(row[5] or ""),
                display_label=_clean_text(row[6]),
                inferred_field_type=_clean_text(row[7]),
                required=bool(row[8]),
                source_occurrence_count=int(row[9] or 0),
                metadata=_json_loads(row[10]),
            )
            for row in rows
        ]

    def list_placeholder_bindings(
        self, revision_id: int
    ) -> list[ContractTemplatePlaceholderBindingRecord]:
        rows = self.conn.execute(
            """
            SELECT
                id,
                revision_id,
                placeholder_id,
                canonical_symbol,
                resolver_kind,
                resolver_target,
                scope_entity_type,
                scope_policy,
                widget_hint,
                validation_json,
                metadata_json,
                created_at,
                updated_at
            FROM ContractTemplatePlaceholderBindings
            WHERE revision_id=?
            ORDER BY canonical_symbol ASC
            """,
            (int(revision_id),),
        ).fetchall()
        return [
            ContractTemplatePlaceholderBindingRecord(
                binding_id=int(row[0]),
                revision_id=int(row[1]),
                placeholder_id=int(row[2]),
                canonical_symbol=str(row[3] or ""),
                resolver_kind=str(row[4] or ""),
                resolver_target=_clean_text(row[5]),
                scope_entity_type=_clean_text(row[6]),
                scope_policy=_clean_text(row[7]),
                widget_hint=_clean_text(row[8]),
                validation=_json_loads(row[9]),
                metadata=_json_loads(row[10]),
                created_at=_clean_text(row[11]),
                updated_at=_clean_text(row[12]),
            )
            for row in rows
        ]

    def replace_placeholder_bindings(
        self,
        revision_id: int,
        *,
        bindings: Iterable[ContractTemplatePlaceholderBindingPayload],
    ) -> list[ContractTemplatePlaceholderBindingRecord]:
        revision = self.fetch_revision(revision_id)
        if revision is None:
            raise ValueError(f"Contract template revision {revision_id} not found")
        placeholders = [
            self._placeholder_payload_from_record(item)
            for item in self.list_placeholders(revision_id)
        ]
        self.replace_revision_placeholder_inventory(
            revision_id,
            placeholders=placeholders,
            bindings=bindings,
            scan_status=revision.scan_status,
            scan_error=revision.scan_error,
            scan_adapter=revision.scan_adapter,
            scan_diagnostics=revision.scan_diagnostics,
        )
        return self.list_placeholder_bindings(revision_id)

    def create_draft(self, payload: ContractTemplateDraftPayload) -> ContractTemplateDraftRecord:
        clean_mode = normalize_storage_mode(payload.storage_mode, default=STORAGE_MODE_DATABASE)
        clean_filename = coalesce_filename(
            payload.filename,
            default_stem=str(payload.name or "contract-template-draft"),
            default_suffix=".json",
        )
        payload_bytes = self._serialize_editable_payload(payload.editable_payload)
        managed_file_path = None
        sqlite_blob: bytes | sqlite3.Binary | None = None
        if clean_mode == STORAGE_MODE_DATABASE:
            sqlite_blob = sqlite3.Binary(payload_bytes)
        else:
            managed_file_path = self.draft_store.write_bytes(payload_bytes, filename=clean_filename)
        with self.conn:
            cur = self.conn.cursor()
            cur.execute(
                """
                INSERT INTO ContractTemplateDrafts (
                    revision_id,
                    name,
                    status,
                    scope_entity_type,
                    scope_entity_id,
                    managed_file_path,
                    storage_mode,
                    payload_blob,
                    filename,
                    mime_type,
                    size_bytes,
                    last_resolved_snapshot_id
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    int(payload.revision_id),
                    str(payload.name or "").strip(),
                    str(payload.status or "draft").strip() or "draft",
                    _clean_text(payload.scope_entity_type),
                    _clean_text(payload.scope_entity_id),
                    managed_file_path,
                    clean_mode,
                    sqlite_blob,
                    clean_filename,
                    _clean_text(payload.mime_type) or "application/json",
                    len(payload_bytes),
                    (
                        int(payload.last_resolved_snapshot_id)
                        if payload.last_resolved_snapshot_id is not None
                        else None
                    ),
                ),
            )
            draft_id = int(cur.lastrowid)
        record = self.fetch_draft(draft_id)
        if record is None:
            raise RuntimeError(f"Contract template draft {draft_id} was not created")
        return record

    def update_draft(
        self, draft_id: int, payload: ContractTemplateDraftPayload
    ) -> ContractTemplateDraftRecord:
        current = self.fetch_draft(draft_id)
        if current is None:
            raise ValueError(f"Contract template draft {draft_id} not found")
        clean_mode = normalize_storage_mode(payload.storage_mode, default=current.storage_mode)
        clean_filename = coalesce_filename(
            payload.filename or current.filename,
            default_stem=str(payload.name or current.name or "contract-template-draft"),
            default_suffix=".json",
        )
        payload_bytes = self._serialize_editable_payload(payload.editable_payload)
        stale_path = _clean_text(current.managed_file_path)
        managed_file_path = None
        sqlite_blob: bytes | sqlite3.Binary | None = None
        if clean_mode == STORAGE_MODE_DATABASE:
            sqlite_blob = sqlite3.Binary(payload_bytes)
        else:
            managed_file_path = self.draft_store.write_bytes(payload_bytes, filename=clean_filename)
        with self.conn:
            cur = self.conn.cursor()
            cur.execute(
                """
                UPDATE ContractTemplateDrafts
                SET revision_id=?,
                    name=?,
                    status=?,
                    scope_entity_type=?,
                    scope_entity_id=?,
                    managed_file_path=?,
                    storage_mode=?,
                    payload_blob=?,
                    filename=?,
                    mime_type=?,
                    size_bytes=?,
                    last_resolved_snapshot_id=?,
                    updated_at=datetime('now')
                WHERE id=?
                """,
                (
                    int(payload.revision_id),
                    str(payload.name or current.name).strip(),
                    str(payload.status or current.status or "draft").strip() or "draft",
                    (
                        _clean_text(payload.scope_entity_type)
                        if payload.scope_entity_type is not None
                        else current.scope_entity_type
                    ),
                    (
                        _clean_text(payload.scope_entity_id)
                        if payload.scope_entity_id is not None
                        else current.scope_entity_id
                    ),
                    managed_file_path,
                    clean_mode,
                    sqlite_blob,
                    clean_filename,
                    _clean_text(payload.mime_type) or current.mime_type or "application/json",
                    len(payload_bytes),
                    (
                        int(payload.last_resolved_snapshot_id)
                        if payload.last_resolved_snapshot_id is not None
                        else current.last_resolved_snapshot_id
                    ),
                    int(draft_id),
                ),
            )
            if stale_path and stale_path != _clean_text(managed_file_path):
                self._delete_unreferenced_managed_file(
                    table_name="ContractTemplateDrafts",
                    path_column="managed_file_path",
                    stored_path=stale_path,
                    file_store=self.draft_store,
                    cursor=cur,
                )
        updated = self.fetch_draft(draft_id)
        if updated is None:
            raise RuntimeError(f"Contract template draft {draft_id} disappeared after update")
        return updated

    def fetch_draft(self, draft_id: int) -> ContractTemplateDraftRecord | None:
        row = self.conn.execute(
            """
            SELECT
                id,
                revision_id,
                name,
                status,
                scope_entity_type,
                scope_entity_id,
                managed_file_path,
                storage_mode,
                filename,
                mime_type,
                size_bytes,
                working_file_path,
                working_filename,
                working_mime_type,
                working_size_bytes,
                working_checksum_sha256,
                last_resolved_snapshot_id,
                created_at,
                updated_at,
                CASE WHEN payload_blob IS NOT NULL THEN 1 ELSE 0 END AS has_blob
            FROM ContractTemplateDrafts
            WHERE id=?
            """,
            (int(draft_id),),
        ).fetchone()
        if not row:
            return None
        mode = infer_storage_mode(
            explicit_mode=row[7],
            stored_path=row[6],
            blob_value=b"x" if row[19] else None,
            default=STORAGE_MODE_DATABASE,
        )
        return ContractTemplateDraftRecord(
            draft_id=int(row[0]),
            revision_id=int(row[1]),
            name=str(row[2] or ""),
            status=str(row[3] or "draft"),
            scope_entity_type=_clean_text(row[4]),
            scope_entity_id=_clean_text(row[5]),
            managed_file_path=_clean_text(row[6]),
            storage_mode=mode,
            filename=_clean_text(row[8]),
            mime_type=_clean_text(row[9]),
            size_bytes=int(row[10] or 0),
            working_file_path=_clean_text(row[11]),
            working_filename=_clean_text(row[12]),
            working_mime_type=_clean_text(row[13]),
            working_size_bytes=int(row[14] or 0),
            working_checksum_sha256=_clean_text(row[15]),
            last_resolved_snapshot_id=int(row[16]) if row[16] is not None else None,
            created_at=_clean_text(row[17]),
            updated_at=_clean_text(row[18]),
            stored_in_database=(mode == STORAGE_MODE_DATABASE),
        )

    def list_drafts(
        self,
        *,
        revision_id: int | None = None,
        include_archived: bool = False,
    ) -> list[ContractTemplateDraftRecord]:
        clauses: list[str] = []
        params: list[object] = []
        if not include_archived:
            clauses.append("status != 'archived'")
        if revision_id is not None:
            clauses.append("revision_id=?")
            params.append(int(revision_id))
        where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self.conn.execute(
            f"""
            SELECT id
            FROM ContractTemplateDrafts
            {where_sql}
            ORDER BY updated_at DESC, id DESC
            """,
            params,
        ).fetchall()
        records: list[ContractTemplateDraftRecord] = []
        for row in rows:
            record = self.fetch_draft(int(row[0]))
            if record is not None:
                records.append(record)
        return records

    def list_template_drafts(
        self,
        template_id: int,
        *,
        include_archived: bool = False,
    ) -> list[ContractTemplateDraftRecord]:
        where_sql = "" if include_archived else "AND d.status != 'archived'"
        rows = self.conn.execute(
            f"""
            SELECT d.id
            FROM ContractTemplateDrafts d
            INNER JOIN ContractTemplateRevisions r ON r.id = d.revision_id
            WHERE r.template_id=?
            {where_sql}
            ORDER BY d.updated_at DESC, d.id DESC
            """,
            (int(template_id),),
        ).fetchall()
        return [
            record
            for row in rows
            for record in [self.fetch_draft(int(row[0]))]
            if record is not None
        ]

    def archive_draft(
        self,
        draft_id: int,
        *,
        archived: bool = True,
    ) -> ContractTemplateDraftRecord:
        current = self.fetch_draft(draft_id)
        if current is None:
            raise ValueError(f"Contract template draft {draft_id} not found")
        next_status = "archived" if archived else "draft"
        with self.conn:
            self.conn.execute(
                """
                UPDATE ContractTemplateDrafts
                SET status=?,
                    updated_at=datetime('now')
                WHERE id=?
                """,
                (next_status, int(draft_id)),
            )
        updated = self.fetch_draft(draft_id)
        if updated is None:
            raise RuntimeError(
                f"Contract template draft {draft_id} disappeared after archive update"
            )
        return updated

    def set_draft_last_resolved_snapshot(
        self,
        draft_id: int,
        snapshot_id: int | None,
    ) -> ContractTemplateDraftRecord:
        current = self.fetch_draft(draft_id)
        if current is None:
            raise ValueError(f"Contract template draft {draft_id} not found")
        with self.conn:
            self.conn.execute(
                """
                UPDATE ContractTemplateDrafts
                SET last_resolved_snapshot_id=?,
                    updated_at=datetime('now')
                WHERE id=?
                """,
                (
                    int(snapshot_id) if snapshot_id is not None else None,
                    int(draft_id),
                ),
            )
        updated = self.fetch_draft(draft_id)
        if updated is None:
            raise RuntimeError(
                f"Contract template draft {draft_id} disappeared after snapshot update"
            )
        return updated

    def fetch_draft_payload(self, draft_id: int) -> object | None:
        row = self.conn.execute(
            """
            SELECT payload_blob, managed_file_path, storage_mode, filename
            FROM ContractTemplateDrafts
            WHERE id=?
            """,
            (int(draft_id),),
        ).fetchone()
        if not row:
            raise FileNotFoundError(draft_id)
        blob_value, managed_file_path, storage_mode, filename = row
        mode = infer_storage_mode(
            explicit_mode=storage_mode,
            stored_path=managed_file_path,
            blob_value=blob_value,
            default=STORAGE_MODE_DATABASE,
        )
        if mode == STORAGE_MODE_DATABASE:
            if blob_value is None:
                return None
            payload_bytes = bytes_from_blob(blob_value)
        else:
            resolved = self.draft_store.resolve(managed_file_path)
            if resolved is None or not resolved.exists():
                raise FileNotFoundError(str(managed_file_path or filename or draft_id))
            payload_bytes = resolved.read_bytes()
        text = payload_bytes.decode("utf-8") if payload_bytes else ""
        return _json_loads(text)

    def resolve_draft_working_path(self, draft_id: int) -> Path | None:
        draft = self.fetch_draft(draft_id)
        if draft is None:
            raise ValueError(f"Contract template draft {draft_id} not found")
        clean_path = _clean_text(draft.working_file_path)
        if not clean_path:
            return None
        resolved = self.draft_store.resolve(clean_path)
        if resolved is None or not resolved.exists():
            return None
        return resolved

    def load_draft_working_bytes(self, draft_id: int) -> bytes | None:
        resolved = self.resolve_draft_working_path(draft_id)
        if resolved is None:
            return None
        return resolved.read_bytes()

    def set_draft_working_file(
        self,
        draft_id: int,
        *,
        content_bytes: bytes,
        filename: str,
        mime_type: str,
    ) -> ContractTemplateDraftRecord:
        draft = self.fetch_draft(draft_id)
        if draft is None:
            raise ValueError(f"Contract template draft {draft_id} not found")
        revision = self.fetch_revision(draft.revision_id)
        if revision is None:
            raise ValueError(f"Contract template revision {draft.revision_id} not found")
        subdir = f"html_draft_{draft_id}"
        relative_path = self.draft_store.write_bytes(
            content_bytes,
            filename=filename,
            subdir=subdir,
        )
        resolved = self.draft_store.resolve(relative_path)
        if resolved is None:
            raise RuntimeError("Managed draft storage is not configured.")
        stale_path = _clean_text(draft.working_file_path)
        with self.conn:
            self.conn.execute(
                """
                UPDATE ContractTemplateDrafts
                SET working_file_path=?,
                    working_filename=?,
                    working_mime_type=?,
                    working_size_bytes=?,
                    working_checksum_sha256=?,
                    updated_at=datetime('now')
                WHERE id=?
                """,
                (
                    relative_path,
                    coalesce_filename(filename, default_stem=resolved.stem or "draft"),
                    _clean_text(mime_type) or "text/html",
                    len(content_bytes),
                    sha256_digest(content_bytes),
                    int(draft_id),
                ),
            )
        if stale_path and stale_path != relative_path:
            self._delete_managed_tree_for_path(self.draft_store, stale_path)
        updated = self.fetch_draft(draft_id)
        if updated is None:
            raise RuntimeError(f"Contract template draft {draft_id} disappeared after update")
        return updated

    def set_draft_working_path(
        self,
        draft_id: int,
        *,
        working_path: str | Path,
        mime_type: str = "text/html",
    ) -> ContractTemplateDraftRecord:
        draft = self.fetch_draft(draft_id)
        if draft is None:
            raise ValueError(f"Contract template draft {draft_id} not found")
        candidate = Path(working_path)
        if not candidate.is_absolute():
            resolved = self.draft_store.resolve(str(candidate))
            candidate = resolved if resolved is not None else candidate
        if not candidate.exists():
            raise FileNotFoundError(candidate)
        root_path = self.draft_store.root_path
        if root_path is None or self.data_root is None:
            raise ValueError("Managed draft storage is not configured.")
        try:
            relative = candidate.resolve().relative_to(self.data_root.resolve())
            candidate.resolve().relative_to(root_path.resolve())
        except Exception as exc:
            raise ValueError(
                "Draft working paths must stay inside managed contract template draft storage."
            ) from exc
        data = candidate.read_bytes()
        stale_path = _clean_text(draft.working_file_path)
        with self.conn:
            self.conn.execute(
                """
                UPDATE ContractTemplateDrafts
                SET working_file_path=?,
                    working_filename=?,
                    working_mime_type=?,
                    working_size_bytes=?,
                    working_checksum_sha256=?,
                    updated_at=datetime('now')
                WHERE id=?
                """,
                (
                    str(relative),
                    candidate.name,
                    _clean_text(mime_type) or "text/html",
                    len(data),
                    sha256_digest(data),
                    int(draft_id),
                ),
            )
        if stale_path and stale_path != str(relative):
            self._delete_managed_tree_for_path(self.draft_store, stale_path)
        updated = self.fetch_draft(draft_id)
        if updated is None:
            raise RuntimeError(f"Contract template draft {draft_id} disappeared after update")
        return updated

    def clear_draft_working_file(self, draft_id: int) -> ContractTemplateDraftRecord:
        draft = self.fetch_draft(draft_id)
        if draft is None:
            raise ValueError(f"Contract template draft {draft_id} not found")
        stale_path = _clean_text(draft.working_file_path)
        with self.conn:
            self.conn.execute(
                """
                UPDATE ContractTemplateDrafts
                SET working_file_path=NULL,
                    working_filename=NULL,
                    working_mime_type=NULL,
                    working_size_bytes=0,
                    working_checksum_sha256=NULL,
                    updated_at=datetime('now')
                WHERE id=?
                """,
                (int(draft_id),),
            )
        if stale_path:
            self._delete_managed_tree_for_path(self.draft_store, stale_path)
        updated = self.fetch_draft(draft_id)
        if updated is None:
            raise RuntimeError(f"Contract template draft {draft_id} disappeared after update")
        return updated

    def convert_draft_storage_mode(
        self, draft_id: int, target_mode: str
    ) -> ContractTemplateDraftRecord:
        current = self.fetch_draft(draft_id)
        if current is None:
            raise ValueError(f"Contract template draft {draft_id} not found")
        clean_mode = normalize_storage_mode(target_mode)
        if current.storage_mode == clean_mode:
            return current
        payload_obj = self.fetch_draft_payload(draft_id)
        update_payload = ContractTemplateDraftPayload(
            revision_id=current.revision_id,
            name=current.name,
            editable_payload=payload_obj,
            status=current.status,
            scope_entity_type=current.scope_entity_type,
            scope_entity_id=current.scope_entity_id,
            storage_mode=clean_mode,
            filename=current.filename,
            mime_type=current.mime_type or "application/json",
            last_resolved_snapshot_id=current.last_resolved_snapshot_id,
        )
        return self.update_draft(draft_id, update_payload)

    def create_resolved_snapshot(
        self, payload: ContractTemplateResolvedSnapshotPayload
    ) -> ContractTemplateResolvedSnapshotRecord:
        resolved_values_json = _json_dumps(payload.resolved_values) or "{}"
        resolution_warnings_json = _json_dumps(payload.resolution_warnings)
        preview_payload_json = _json_dumps(payload.preview_payload)
        checksum = _clean_text(payload.resolved_checksum_sha256) or sha256_digest(
            resolved_values_json.encode("utf-8")
        )
        with self.conn:
            cur = self.conn.cursor()
            cur.execute(
                """
                INSERT INTO ContractTemplateResolvedSnapshots (
                    draft_id,
                    revision_id,
                    scope_entity_type,
                    scope_entity_id,
                    resolved_values_json,
                    resolution_warnings_json,
                    preview_payload_json,
                    resolved_checksum_sha256
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    int(payload.draft_id),
                    int(payload.revision_id),
                    _clean_text(payload.scope_entity_type),
                    _clean_text(payload.scope_entity_id),
                    resolved_values_json,
                    resolution_warnings_json,
                    preview_payload_json,
                    checksum,
                ),
            )
            snapshot_id = int(cur.lastrowid)
        record = self.fetch_resolved_snapshot(snapshot_id)
        if record is None:
            raise RuntimeError(f"Contract template snapshot {snapshot_id} was not created")
        return record

    def fetch_resolved_snapshot(
        self, snapshot_id: int
    ) -> ContractTemplateResolvedSnapshotRecord | None:
        row = self.conn.execute(
            """
            SELECT
                id,
                draft_id,
                revision_id,
                scope_entity_type,
                scope_entity_id,
                resolved_values_json,
                resolution_warnings_json,
                preview_payload_json,
                resolved_checksum_sha256,
                created_at
            FROM ContractTemplateResolvedSnapshots
            WHERE id=?
            """,
            (int(snapshot_id),),
        ).fetchone()
        if not row:
            return None
        return ContractTemplateResolvedSnapshotRecord(
            snapshot_id=int(row[0]),
            draft_id=int(row[1]),
            revision_id=int(row[2]),
            scope_entity_type=_clean_text(row[3]),
            scope_entity_id=_clean_text(row[4]),
            resolved_values=_json_loads(row[5]),
            resolution_warnings=_json_loads(row[6]),
            preview_payload=_json_loads(row[7]),
            resolved_checksum_sha256=_clean_text(row[8]),
            created_at=_clean_text(row[9]),
        )

    def list_resolved_snapshots(
        self, *, draft_id: int | None = None
    ) -> list[ContractTemplateResolvedSnapshotRecord]:
        if draft_id is None:
            rows = self.conn.execute(
                "SELECT id FROM ContractTemplateResolvedSnapshots ORDER BY created_at DESC, id DESC"
            ).fetchall()
        else:
            rows = self.conn.execute(
                """
                SELECT id
                FROM ContractTemplateResolvedSnapshots
                WHERE draft_id=?
                ORDER BY created_at DESC, id DESC
                """,
                (int(draft_id),),
            ).fetchall()
        records: list[ContractTemplateResolvedSnapshotRecord] = []
        for row in rows:
            record = self.fetch_resolved_snapshot(int(row[0]))
            if record is not None:
                records.append(record)
        return records

    def list_template_resolved_snapshots(
        self, template_id: int
    ) -> list[ContractTemplateResolvedSnapshotRecord]:
        rows = self.conn.execute(
            """
            SELECT s.id
            FROM ContractTemplateResolvedSnapshots s
            INNER JOIN ContractTemplateRevisions r ON r.id = s.revision_id
            WHERE r.template_id=?
            ORDER BY s.created_at DESC, s.id DESC
            """,
            (int(template_id),),
        ).fetchall()
        return [
            record
            for row in rows
            for record in [self.fetch_resolved_snapshot(int(row[0]))]
            if record is not None
        ]

    def create_output_artifact(
        self, payload: ContractTemplateOutputArtifactPayload
    ) -> ContractTemplateOutputArtifactRecord:
        clean_output_path = str(payload.output_path or "").strip()
        if not clean_output_path:
            raise ValueError("Output artifact path is required")
        clean_output_filename = coalesce_filename(
            payload.output_filename,
            stored_path=clean_output_path,
            default_stem=Path(clean_output_path).stem or "artifact",
        )
        with self.conn:
            cur = self.conn.cursor()
            cur.execute(
                """
                INSERT INTO ContractTemplateOutputArtifacts (
                    snapshot_id,
                    artifact_type,
                    status,
                    output_path,
                    output_filename,
                    mime_type,
                    size_bytes,
                    checksum_sha256,
                    retained
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    int(payload.snapshot_id),
                    str(payload.artifact_type or "").strip(),
                    str(payload.status or "generated").strip() or "generated",
                    clean_output_path,
                    clean_output_filename,
                    _clean_text(payload.mime_type),
                    max(0, int(payload.size_bytes or 0)),
                    _clean_text(payload.checksum_sha256),
                    1 if payload.retained else 0,
                ),
            )
            artifact_id = int(cur.lastrowid)
        record = self.fetch_output_artifact(artifact_id)
        if record is None:
            raise RuntimeError(f"Contract template output artifact {artifact_id} was not created")
        return record

    def fetch_output_artifact(
        self, artifact_id: int
    ) -> ContractTemplateOutputArtifactRecord | None:
        row = self.conn.execute(
            """
            SELECT
                id,
                snapshot_id,
                artifact_type,
                status,
                output_path,
                output_filename,
                mime_type,
                size_bytes,
                checksum_sha256,
                retained,
                created_at
            FROM ContractTemplateOutputArtifacts
            WHERE id=?
            """,
            (int(artifact_id),),
        ).fetchone()
        if not row:
            return None
        return ContractTemplateOutputArtifactRecord(
            artifact_id=int(row[0]),
            snapshot_id=int(row[1]),
            artifact_type=str(row[2] or ""),
            status=str(row[3] or "generated"),
            output_path=str(row[4] or ""),
            output_filename=str(row[5] or ""),
            mime_type=_clean_text(row[6]),
            size_bytes=int(row[7] or 0),
            checksum_sha256=_clean_text(row[8]),
            retained=bool(row[9]),
            created_at=_clean_text(row[10]),
        )

    def list_output_artifacts(
        self, *, snapshot_id: int | None = None
    ) -> list[ContractTemplateOutputArtifactRecord]:
        if snapshot_id is None:
            rows = self.conn.execute(
                "SELECT id FROM ContractTemplateOutputArtifacts ORDER BY created_at DESC, id DESC"
            ).fetchall()
        else:
            rows = self.conn.execute(
                """
                SELECT id
                FROM ContractTemplateOutputArtifacts
                WHERE snapshot_id=?
                ORDER BY created_at DESC, id DESC
                """,
                (int(snapshot_id),),
            ).fetchall()
        records: list[ContractTemplateOutputArtifactRecord] = []
        for row in rows:
            record = self.fetch_output_artifact(int(row[0]))
            if record is not None:
                records.append(record)
        return records

    def list_template_output_artifacts(
        self, template_id: int
    ) -> list[ContractTemplateOutputArtifactRecord]:
        rows = self.conn.execute(
            """
            SELECT a.id
            FROM ContractTemplateOutputArtifacts a
            INNER JOIN ContractTemplateResolvedSnapshots s ON s.id = a.snapshot_id
            INNER JOIN ContractTemplateRevisions r ON r.id = s.revision_id
            WHERE r.template_id=?
            ORDER BY a.created_at DESC, a.id DESC
            """,
            (int(template_id),),
        ).fetchall()
        return [
            record
            for row in rows
            for record in [self.fetch_output_artifact(int(row[0]))]
            if record is not None
        ]

    def delete_output_artifact(
        self,
        artifact_id: int,
        *,
        remove_file: bool = False,
    ) -> None:
        record = self.fetch_output_artifact(artifact_id)
        if record is None:
            raise ValueError(f"Contract template output artifact {artifact_id} not found")
        with self.conn:
            self.conn.execute(
                "DELETE FROM ContractTemplateOutputArtifacts WHERE id=?",
                (int(artifact_id),),
            )
        if remove_file:
            self._delete_artifact_file(record.output_path)

    def delete_draft(
        self,
        draft_id: int,
        *,
        remove_managed_payload: bool = False,
        remove_output_files: bool = False,
    ) -> None:
        current = self.fetch_draft(draft_id)
        if current is None:
            raise ValueError(f"Contract template draft {draft_id} not found")
        payload_path = _clean_text(current.managed_file_path) if remove_managed_payload else None
        html_working_copy_path = (
            _clean_text(current.working_file_path) if remove_managed_payload else None
        )
        snapshots = tuple(self.list_resolved_snapshots(draft_id=draft_id))
        snapshot_ids = [snapshot.snapshot_id for snapshot in snapshots]
        artifact_ids = [
            artifact.artifact_id
            for snapshot in snapshots
            for artifact in self.list_output_artifacts(snapshot_id=snapshot.snapshot_id)
        ]
        artifact_paths = (
            [
                artifact.output_path
                for snapshot in snapshots
                for artifact in self.list_output_artifacts(snapshot_id=snapshot.snapshot_id)
            ]
            if remove_output_files
            else []
        )
        with self.conn:
            if artifact_ids:
                self._delete_rows_for_ids(
                    "ContractTemplateOutputArtifacts",
                    artifact_ids,
                    cursor=self.conn.cursor(),
                )
            if snapshot_ids:
                self._delete_rows_for_ids(
                    "ContractTemplateResolvedSnapshots",
                    snapshot_ids,
                    cursor=self.conn.cursor(),
                )
            self.conn.execute(
                "DELETE FROM ContractTemplateDrafts WHERE id=?",
                (int(draft_id),),
            )
        if payload_path:
            resolved = self.draft_store.resolve(payload_path)
            if resolved is not None:
                try:
                    resolved.unlink(missing_ok=True)
                except Exception:
                    pass
        if html_working_copy_path:
            self._delete_managed_tree_for_path(self.draft_store, html_working_copy_path)
        for artifact_path in artifact_paths:
            self._delete_artifact_file(artifact_path)

    def delete_template(
        self,
        template_id: int,
        *,
        remove_source_files: bool = False,
        remove_draft_files: bool = False,
        remove_output_files: bool = False,
    ) -> None:
        template = self.fetch_template(template_id)
        if template is None:
            raise ValueError(f"Contract template {template_id} not found")
        revisions = tuple(self.list_revisions(template_id))
        revision_ids = [record.revision_id for record in revisions]
        drafts = tuple(self.list_template_drafts(template_id, include_archived=True))
        draft_ids = [record.draft_id for record in drafts]
        snapshots = tuple(self.list_template_resolved_snapshots(template_id))
        snapshot_ids = [snapshot.snapshot_id for snapshot in snapshots]
        artifacts = tuple(self.list_template_output_artifacts(template_id))
        artifact_ids = [artifact.artifact_id for artifact in artifacts]
        source_paths = [
            record.managed_file_path
            for record in revisions
            if remove_source_files and _clean_text(record.managed_file_path)
        ]
        draft_paths = [
            record.managed_file_path
            for record in drafts
            if remove_draft_files and _clean_text(record.managed_file_path)
        ]
        draft_html_paths = (
            [_clean_text(record.working_file_path) for record in drafts]
            if remove_draft_files
            else []
        )
        artifact_paths = (
            [artifact.output_path for artifact in artifacts] if remove_output_files else []
        )
        with self.conn:
            if artifact_ids:
                self._delete_rows_for_ids(
                    "ContractTemplateOutputArtifacts",
                    artifact_ids,
                    cursor=self.conn.cursor(),
                )
            if snapshot_ids:
                self._delete_rows_for_ids(
                    "ContractTemplateResolvedSnapshots",
                    snapshot_ids,
                    cursor=self.conn.cursor(),
                )
            if draft_ids:
                self._delete_rows_for_ids(
                    "ContractTemplateDrafts",
                    draft_ids,
                    cursor=self.conn.cursor(),
                )
            if revision_ids:
                cursor = self.conn.cursor()
                cursor.execute(
                    f"DELETE FROM ContractTemplateRevisionAssets WHERE revision_id IN ({','.join('?' for _ in revision_ids)})",
                    tuple(int(revision_id) for revision_id in revision_ids),
                )
                cursor.execute(
                    f"DELETE FROM ContractTemplatePlaceholderBindings WHERE revision_id IN ({','.join('?' for _ in revision_ids)})",
                    tuple(int(revision_id) for revision_id in revision_ids),
                )
                cursor.execute(
                    f"DELETE FROM ContractTemplatePlaceholders WHERE revision_id IN ({','.join('?' for _ in revision_ids)})",
                    tuple(int(revision_id) for revision_id in revision_ids),
                )
                self._delete_rows_for_ids(
                    "ContractTemplateRevisions",
                    revision_ids,
                    cursor=cursor,
                )
            self.conn.execute(
                "DELETE FROM ContractTemplates WHERE id=?",
                (int(template_id),),
            )
        for stored_path in source_paths:
            self._delete_managed_tree_for_path(self.source_store, stored_path)
        for stored_path in draft_paths:
            resolved = self.draft_store.resolve(stored_path)
            if resolved is not None:
                try:
                    resolved.unlink(missing_ok=True)
                except Exception:
                    pass
        for stored_path in draft_html_paths:
            if stored_path:
                self._delete_managed_tree_for_path(self.draft_store, stored_path)
        for artifact_path in artifact_paths:
            self._delete_artifact_file(artifact_path)

    @staticmethod
    def _serialize_editable_payload(value: object | None) -> bytes:
        text = _json_dumps(value)
        if text is None:
            text = "{}"
        return text.encode("utf-8")

    @staticmethod
    def _placeholder_payload_from_record(
        record: ContractTemplatePlaceholderRecord,
    ) -> ContractTemplatePlaceholderPayload:
        return ContractTemplatePlaceholderPayload(
            canonical_symbol=record.canonical_symbol,
            display_label=record.display_label,
            inferred_field_type=record.inferred_field_type,
            required=record.required,
            source_occurrence_count=record.source_occurrence_count,
            metadata=record.metadata,
        )

    @staticmethod
    def _binding_payload_from_record(
        record: ContractTemplatePlaceholderBindingRecord,
    ) -> ContractTemplatePlaceholderBindingPayload:
        return ContractTemplatePlaceholderBindingPayload(
            canonical_symbol=record.canonical_symbol,
            resolver_kind=record.resolver_kind,
            resolver_target=record.resolver_target,
            scope_entity_type=record.scope_entity_type,
            scope_policy=record.scope_policy,
            widget_hint=record.widget_hint,
            validation=record.validation,
            metadata=record.metadata,
        )

    def _html_asset_payloads_for_source(
        self,
        managed_file_path: str,
    ) -> tuple[ContractTemplateRevisionAssetPayload, ...]:
        resolved_primary = self.source_store.resolve(managed_file_path)
        root_path = self.source_store.root_path
        if (
            resolved_primary is None
            or root_path is None
            or self.data_root is None
            or not resolved_primary.exists()
        ):
            return ()
        try:
            relative = resolved_primary.resolve().relative_to(root_path.resolve())
        except Exception:
            return ()
        bundle_root = root_path / relative.parts[0] if relative.parts else resolved_primary.parent
        assets: list[ContractTemplateRevisionAssetPayload] = []
        for path in sorted(item for item in bundle_root.rglob("*") if item.is_file()):
            if path.resolve() == resolved_primary.resolve():
                continue
            data = path.read_bytes()
            assets.append(
                ContractTemplateRevisionAssetPayload(
                    package_rel_path=path.relative_to(bundle_root).as_posix(),
                    managed_file_path=str(path.relative_to(self.data_root)),
                    source_filename=path.name,
                    mime_type=guess_mime_type(path.name),
                    size_bytes=len(data),
                    checksum_sha256=sha256_digest(data),
                    asset_role="asset",
                )
            )
        return tuple(assets)

    def _delete_artifact_file(self, output_path: str | None) -> None:
        clean_path = str(output_path or "").strip()
        if not clean_path:
            return
        candidate = Path(clean_path)
        if not candidate.is_absolute():
            resolved = self.artifact_store.resolve(clean_path)
            candidate = resolved if resolved is not None else candidate
        root_path = self.artifact_store.root_path
        if root_path is None:
            raise ValueError("Managed artifact storage is not configured")
        try:
            candidate.resolve().relative_to(root_path.resolve())
        except Exception as exc:
            raise ValueError(
                "Artifact file removal is only allowed for managed contract template artifacts."
            ) from exc
        try:
            candidate.unlink(missing_ok=True)
        except Exception:
            pass

    def _delete_managed_tree_for_path(
        self,
        file_store: ManagedFileStorage,
        stored_path: str | None,
    ) -> None:
        clean_path = _clean_text(stored_path)
        if not clean_path:
            return
        resolved = file_store.resolve(clean_path)
        if resolved is None:
            return
        root_path = file_store.root_path
        if root_path is None:
            return
        try:
            relative = resolved.resolve().relative_to(root_path.resolve())
        except Exception:
            return
        target = resolved
        if len(relative.parts) > 1:
            target = root_path / relative.parts[0]
        try:
            if target.is_dir():
                shutil.rmtree(target, ignore_errors=True)
            else:
                target.unlink(missing_ok=True)
        except Exception:
            pass

    @staticmethod
    def _delete_unreferenced_managed_file(
        *,
        table_name: str,
        path_column: str,
        stored_path: str | None,
        file_store: ManagedFileStorage,
        cursor: sqlite3.Cursor,
    ) -> None:
        clean_path = _clean_text(stored_path)
        if not clean_path or not file_store.is_managed(clean_path):
            return
        row = cursor.execute(
            f"SELECT 1 FROM {table_name} WHERE {path_column}=? LIMIT 1",
            (clean_path,),
        ).fetchone()
        if row:
            return
        resolved = file_store.resolve(clean_path)
        if resolved is None:
            return
        try:
            resolved.unlink(missing_ok=True)
        except Exception:
            pass

    @staticmethod
    def _delete_rows_for_ids(
        table_name: str,
        row_ids: list[int],
        *,
        cursor: sqlite3.Cursor,
    ) -> None:
        clean_ids = [int(row_id) for row_id in row_ids]
        if not clean_ids:
            return
        placeholders = ",".join("?" for _ in clean_ids)
        cursor.execute(
            f"DELETE FROM {table_name} WHERE id IN ({placeholders})",
            tuple(clean_ids),
        )
