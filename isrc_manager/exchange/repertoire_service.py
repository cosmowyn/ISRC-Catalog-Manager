"""Exchange helpers for works, parties, contracts, rights, and assets."""

from __future__ import annotations

import csv
import json
import shutil
import sqlite3
import tempfile
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from openpyxl import Workbook, load_workbook

from isrc_manager.assets import AssetService, AssetVersionPayload
from isrc_manager.contracts import (
    ContractDocumentPayload,
    ContractObligationPayload,
    ContractPartyPayload,
    ContractPayload,
    ContractService,
)
from isrc_manager.parties import PartyPayload, PartyService
from isrc_manager.rights import RightPayload, RightsService
from isrc_manager.works import WorkContributorPayload, WorkPayload, WorkService

REPERTOIRE_JSON_SCHEMA_VERSION = 1


class RepertoireExchangeService:
    """Imports and exports the expanded repertoire knowledge model."""

    ENTITY_FILENAMES = {
        "parties": "parties.csv",
        "works": "works.csv",
        "contracts": "contracts.csv",
        "rights": "rights.csv",
        "assets": "assets.csv",
    }

    def __init__(
        self,
        conn: sqlite3.Connection,
        *,
        party_service: PartyService,
        work_service: WorkService,
        contract_service: ContractService,
        rights_service: RightsService,
        asset_service: AssetService,
        data_root: str | Path | None = None,
    ):
        self.conn = conn
        self.party_service = party_service
        self.work_service = work_service
        self.contract_service = contract_service
        self.rights_service = rights_service
        self.asset_service = asset_service
        self.data_root = Path(data_root) if data_root is not None else None

    def export_payload(self) -> dict[str, object]:
        return {
            "schema_version": REPERTOIRE_JSON_SCHEMA_VERSION,
            "parties": self.party_service.export_rows(),
            "works": self.work_service.export_rows(),
            "contracts": self.contract_service.export_rows(),
            "rights": self.rights_service.export_rows(),
            "assets": self.asset_service.export_rows(),
        }

    def export_json(self, path: str | Path) -> None:
        output = Path(path)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(self.export_payload(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def export_xlsx(self, path: str | Path) -> None:
        workbook = Workbook()
        payload = self.export_payload()
        default_sheet = workbook.active
        workbook.remove(default_sheet)
        for sheet_name in ("parties", "works", "contracts", "rights", "assets"):
            rows = [dict(row) for row in payload.get(sheet_name, [])]
            sheet = workbook.create_sheet(sheet_name.title())
            headers = sorted({key for row in rows for key in row}) if rows else ["id"]
            sheet.append(headers)
            for row in rows:
                values = []
                for header in headers:
                    value = row.get(header)
                    if isinstance(value, (dict, list)):
                        values.append(json.dumps(value, ensure_ascii=True))
                    else:
                        values.append(value)
                sheet.append(values)
        output = Path(path)
        output.parent.mkdir(parents=True, exist_ok=True)
        workbook.save(output)

    def export_csv_bundle(self, directory: str | Path) -> None:
        output_dir = Path(directory)
        output_dir.mkdir(parents=True, exist_ok=True)
        payload = self.export_payload()
        for entity_name, filename in self.ENTITY_FILENAMES.items():
            rows = [dict(row) for row in payload.get(entity_name, [])]
            headers = sorted({key for row in rows for key in row}) if rows else ["id"]
            with (output_dir / filename).open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=headers)
                writer.writeheader()
                for row in rows:
                    writer.writerow(
                        {
                            key: (
                                json.dumps(value, ensure_ascii=True)
                                if isinstance(value, (dict, list))
                                else value
                            )
                            for key, value in row.items()
                        }
                    )

    def export_package(self, path: str | Path) -> None:
        payload = self.export_payload()
        packaged_files: dict[str, str] = {}
        package_path = Path(path)
        package_path.parent.mkdir(parents=True, exist_ok=True)
        with ZipFile(package_path, "w", compression=ZIP_DEFLATED) as archive:
            for contract in payload["contracts"]:
                for document in contract.get("documents", []):
                    stored_path = str(document.get("file_path") or "").strip()
                    abs_path = self.contract_service.resolve_document_path(stored_path)
                    if not stored_path or abs_path is None or not abs_path.exists():
                        continue
                    arcname = f"files/contracts/{Path(stored_path).name}"
                    if arcname not in packaged_files.values():
                        archive.write(abs_path, arcname=arcname)
                    packaged_files[stored_path] = arcname
            for asset in payload["assets"]:
                stored_path = str(asset.get("stored_path") or "").strip()
                abs_path = self.asset_service.resolve_asset_path(stored_path)
                if not stored_path or abs_path is None or not abs_path.exists():
                    continue
                arcname = f"files/assets/{Path(stored_path).name}"
                if arcname not in packaged_files.values():
                    archive.write(abs_path, arcname=arcname)
                packaged_files[stored_path] = arcname
            payload["packaged_files"] = packaged_files
            archive.writestr("manifest.json", json.dumps(payload, indent=2, ensure_ascii=False))

    def _load_json_payload(self, path: str | Path) -> dict[str, object]:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        version = int(payload.get("schema_version") or 0)
        if version != REPERTOIRE_JSON_SCHEMA_VERSION:
            raise ValueError(
                f"Unsupported repertoire JSON schema version {version}. Expected {REPERTOIRE_JSON_SCHEMA_VERSION}."
            )
        return payload

    def _rows_from_workbook(self, path: str | Path) -> dict[str, list[dict[str, object]]]:
        workbook = load_workbook(filename=str(path), read_only=True, data_only=True)
        rows_by_sheet: dict[str, list[dict[str, object]]] = {}
        for sheet in workbook.worksheets:
            values = list(sheet.iter_rows(values_only=True))
            if not values:
                rows_by_sheet[sheet.title.casefold()] = []
                continue
            headers = [str(value or "").strip() for value in values[0]]
            rows_by_sheet[sheet.title.casefold()] = [
                {headers[index]: row[index] for index in range(len(headers))} for row in values[1:]
            ]
        return rows_by_sheet

    def _rows_from_csv_bundle(self, directory: str | Path) -> dict[str, list[dict[str, object]]]:
        source_dir = Path(directory)
        rows_by_entity: dict[str, list[dict[str, object]]] = {}
        for entity_name, filename in self.ENTITY_FILENAMES.items():
            path = source_dir / filename
            if not path.exists():
                rows_by_entity[entity_name] = []
                continue
            with path.open("r", encoding="utf-8-sig", newline="") as handle:
                rows_by_entity[entity_name] = [dict(row) for row in csv.DictReader(handle)]
        return rows_by_entity

    @staticmethod
    def _decode_value(value: object) -> object:
        if isinstance(value, str):
            text = value.strip()
            if not text:
                return ""
            if text.startswith("[") or text.startswith("{"):
                try:
                    return json.loads(text)
                except Exception:
                    return value
        return value

    def import_json(self, path: str | Path) -> None:
        self._import_payload(self._load_json_payload(path))

    def import_xlsx(self, path: str | Path) -> None:
        rows = self._rows_from_workbook(path)
        self._import_payload(
            {
                "schema_version": REPERTOIRE_JSON_SCHEMA_VERSION,
                "parties": rows.get("parties", []),
                "works": rows.get("works", []),
                "contracts": rows.get("contracts", []),
                "rights": rows.get("rights", []),
                "assets": rows.get("assets", []),
            }
        )

    def import_csv_bundle(self, directory: str | Path) -> None:
        rows = self._rows_from_csv_bundle(directory)
        self._import_payload(
            {
                "schema_version": REPERTOIRE_JSON_SCHEMA_VERSION,
                "parties": rows.get("parties", []),
                "works": rows.get("works", []),
                "contracts": rows.get("contracts", []),
                "rights": rows.get("rights", []),
                "assets": rows.get("assets", []),
            }
        )

    def import_package(self, path: str | Path) -> None:
        with tempfile.TemporaryDirectory(prefix="repertoire-package-") as tmpdir:
            target_dir = Path(tmpdir)
            with ZipFile(path, "r") as archive:
                archive.extractall(target_dir)
            payload = json.loads((target_dir / "manifest.json").read_text(encoding="utf-8"))
            packaged_files = payload.get("packaged_files", {})
            if isinstance(packaged_files, dict):
                for contract in payload.get("contracts", []):
                    for document in contract.get("documents", []):
                        stored_path = str(document.get("file_path") or "").strip()
                        arcname = packaged_files.get(stored_path)
                        if arcname:
                            document["source_path"] = str(target_dir / arcname)
                for asset in payload.get("assets", []):
                    stored_path = str(asset.get("stored_path") or "").strip()
                    arcname = packaged_files.get(stored_path)
                    if arcname:
                        asset["source_path"] = str(target_dir / arcname)
            self._import_payload(payload)

    def _import_payload(self, payload: dict[str, object]) -> None:
        version = int(payload.get("schema_version") or 0)
        if version != REPERTOIRE_JSON_SCHEMA_VERSION:
            raise ValueError(
                f"Unsupported repertoire schema version {version}. Expected {REPERTOIRE_JSON_SCHEMA_VERSION}."
            )
        party_id_map: dict[int, int] = {}
        work_id_map: dict[int, int] = {}
        contract_id_map: dict[int, int] = {}
        document_id_map: dict[int, int] = {}

        with self.conn:
            for row in payload.get("parties", []) or []:
                source = {key: self._decode_value(value) for key, value in dict(row).items()}
                old_id = int(source.get("id") or 0)
                legal_name = str(source.get("legal_name") or "").strip()
                existing = self.conn.execute(
                    "SELECT id FROM Parties WHERE legal_name=? ORDER BY id LIMIT 1",
                    (legal_name,),
                ).fetchone()
                if existing:
                    party_id_map[old_id] = int(existing[0])
                    continue
                new_id = self.party_service.create_party(
                    PartyPayload(
                        legal_name=legal_name,
                        display_name=source.get("display_name"),
                        party_type=source.get("party_type") or "organization",
                        contact_person=source.get("contact_person"),
                        email=source.get("email"),
                        phone=source.get("phone"),
                        website=source.get("website"),
                        address_line1=source.get("address_line1"),
                        address_line2=source.get("address_line2"),
                        city=source.get("city"),
                        region=source.get("region"),
                        postal_code=source.get("postal_code"),
                        country=source.get("country"),
                        tax_id=source.get("tax_id"),
                        vat_number=source.get("vat_number"),
                        pro_affiliation=source.get("pro_affiliation"),
                        ipi_cae=source.get("ipi_cae"),
                        notes=source.get("notes"),
                        profile_name=source.get("profile_name"),
                    ),
                    cursor=self.conn.cursor(),
                )
                party_id_map[old_id] = new_id

            for row in payload.get("works", []) or []:
                source = {key: self._decode_value(value) for key, value in dict(row).items()}
                old_id = int(source.get("id") or 0)
                contributors = []
                for contributor in source.get("contributors", []) or []:
                    contributors.append(
                        WorkContributorPayload(
                            role=contributor.get("role") or "songwriter",
                            name=contributor.get("display_name") or "",
                            share_percent=contributor.get("share_percent"),
                            role_share_percent=contributor.get("role_share_percent"),
                            party_id=party_id_map.get(int(contributor.get("party_id") or 0)),
                            notes=contributor.get("notes"),
                        )
                    )
                track_ids = [
                    int(track_id)
                    for track_id in source.get("track_ids", []) or []
                    if self.conn.execute(
                        "SELECT 1 FROM Tracks WHERE id=?", (int(track_id),)
                    ).fetchone()
                ]
                new_id = self.work_service.create_work(
                    WorkPayload(
                        title=source.get("title") or "",
                        alternate_titles=list(source.get("alternate_titles", []) or []),
                        version_subtitle=source.get("version_subtitle"),
                        language=source.get("language"),
                        lyrics_flag=bool(source.get("lyrics_flag")),
                        instrumental_flag=bool(source.get("instrumental_flag")),
                        genre_notes=source.get("genre_notes"),
                        iswc=source.get("iswc"),
                        registration_number=source.get("registration_number"),
                        work_status=source.get("work_status"),
                        metadata_complete=bool(source.get("metadata_complete")),
                        contract_signed=bool(source.get("contract_signed")),
                        rights_verified=bool(source.get("rights_verified")),
                        notes=source.get("notes"),
                        profile_name=source.get("profile_name"),
                        contributors=contributors,
                        track_ids=track_ids,
                    ),
                    cursor=self.conn.cursor(),
                )
                work_id_map[old_id] = new_id

            contract_documents_buffer: list[tuple[int, list[dict[str, object]]]] = []
            for row in payload.get("contracts", []) or []:
                source = {key: self._decode_value(value) for key, value in dict(row).items()}
                old_id = int(source.get("id") or 0)
                party_payloads = []
                for party in source.get("parties", []) or []:
                    mapped_party_id = party_id_map.get(int(party.get("party_id") or 0))
                    if not mapped_party_id:
                        continue
                    party_payloads.append(
                        ContractPartyPayload(
                            party_id=mapped_party_id,
                            role_label=party.get("role_label") or "counterparty",
                            is_primary=bool(party.get("is_primary")),
                            notes=party.get("notes"),
                        )
                    )
                obligation_payloads = [
                    ContractObligationPayload(
                        obligation_type=item.get("obligation_type") or "other",
                        title=item.get("title") or "",
                        due_date=item.get("due_date"),
                        follow_up_date=item.get("follow_up_date"),
                        reminder_date=item.get("reminder_date"),
                        completed=bool(item.get("completed")),
                        completed_at=item.get("completed_at"),
                        notes=item.get("notes"),
                    )
                    for item in source.get("obligations", []) or []
                ]
                document_payloads = []
                for item in source.get("documents", []) or []:
                    file_source = item.get("source_path") or item.get("file_path")
                    document_payloads.append(
                        ContractDocumentPayload(
                            title=item.get("title") or "",
                            document_type=item.get("document_type") or "other",
                            version_label=item.get("version_label"),
                            created_date=item.get("created_date"),
                            received_date=item.get("received_date"),
                            signed_status=item.get("signed_status"),
                            signed_by_all_parties=bool(item.get("signed_by_all_parties")),
                            active_flag=bool(item.get("active_flag")),
                            source_path=file_source,
                            stored_path=item.get("file_path"),
                            filename=item.get("filename"),
                            checksum_sha256=item.get("checksum_sha256"),
                            notes=item.get("notes"),
                        )
                    )
                work_ids = [
                    work_id_map.get(int(item), 0) for item in source.get("work_ids", []) or []
                ]
                track_ids = [
                    int(item)
                    for item in source.get("track_ids", []) or []
                    if self.conn.execute("SELECT 1 FROM Tracks WHERE id=?", (int(item),)).fetchone()
                ]
                release_ids = [
                    int(item)
                    for item in source.get("release_ids", []) or []
                    if self.conn.execute(
                        "SELECT 1 FROM Releases WHERE id=?", (int(item),)
                    ).fetchone()
                ]
                new_id = self.contract_service.create_contract(
                    ContractPayload(
                        title=source.get("title") or "",
                        contract_type=source.get("contract_type"),
                        draft_date=source.get("draft_date"),
                        signature_date=source.get("signature_date"),
                        effective_date=source.get("effective_date"),
                        start_date=source.get("start_date"),
                        end_date=source.get("end_date"),
                        renewal_date=source.get("renewal_date"),
                        notice_deadline=source.get("notice_deadline"),
                        option_periods=source.get("option_periods"),
                        reversion_date=source.get("reversion_date"),
                        termination_date=source.get("termination_date"),
                        status=source.get("status") or "draft",
                        summary=source.get("summary"),
                        notes=source.get("notes"),
                        profile_name=source.get("profile_name"),
                        parties=party_payloads,
                        obligations=obligation_payloads,
                        documents=document_payloads,
                        work_ids=[item for item in work_ids if item],
                        track_ids=track_ids,
                        release_ids=release_ids,
                    ),
                    cursor=self.conn.cursor(),
                )
                contract_id_map[old_id] = new_id
                contract_documents_buffer.append((new_id, list(source.get("documents", []) or [])))

            for new_contract_id, source_documents in contract_documents_buffer:
                detail = self.contract_service.fetch_contract_detail(new_contract_id)
                if detail is None:
                    continue
                local_docs = detail.documents
                for source_doc, local_doc in zip(source_documents, local_docs):
                    old_doc_id = int(source_doc.get("id") or 0)
                    if old_doc_id:
                        document_id_map[old_doc_id] = local_doc.id
                for source_doc in source_documents:
                    local_doc_id = document_id_map.get(int(source_doc.get("id") or 0))
                    if not local_doc_id:
                        continue
                    supersedes_old = int(source_doc.get("supersedes_document_id") or 0)
                    superseded_by_old = int(source_doc.get("superseded_by_document_id") or 0)
                    self.conn.execute(
                        """
                        UPDATE ContractDocuments
                        SET supersedes_document_id=?,
                            superseded_by_document_id=?
                        WHERE id=?
                        """,
                        (
                            document_id_map.get(supersedes_old) if supersedes_old else None,
                            document_id_map.get(superseded_by_old) if superseded_by_old else None,
                            int(local_doc_id),
                        ),
                    )

            for row in payload.get("rights", []) or []:
                source = {key: self._decode_value(value) for key, value in dict(row).items()}
                self.rights_service.create_right(
                    RightPayload(
                        title=source.get("title"),
                        right_type=source.get("right_type") or "other",
                        exclusive_flag=bool(source.get("exclusive_flag")),
                        territory=source.get("territory"),
                        media_use_type=source.get("media_use_type"),
                        start_date=source.get("start_date"),
                        end_date=source.get("end_date"),
                        perpetual_flag=bool(source.get("perpetual_flag")),
                        granted_by_party_id=party_id_map.get(
                            int(source.get("granted_by_party_id") or 0)
                        ),
                        granted_to_party_id=party_id_map.get(
                            int(source.get("granted_to_party_id") or 0)
                        ),
                        retained_by_party_id=party_id_map.get(
                            int(source.get("retained_by_party_id") or 0)
                        ),
                        source_contract_id=contract_id_map.get(
                            int(source.get("source_contract_id") or 0)
                        ),
                        work_id=work_id_map.get(int(source.get("work_id") or 0)),
                        track_id=(
                            int(source.get("track_id"))
                            if source.get("track_id")
                            and self.conn.execute(
                                "SELECT 1 FROM Tracks WHERE id=?",
                                (int(source.get("track_id")),),
                            ).fetchone()
                            else None
                        ),
                        release_id=(
                            int(source.get("release_id"))
                            if source.get("release_id")
                            and self.conn.execute(
                                "SELECT 1 FROM Releases WHERE id=?",
                                (int(source.get("release_id")),),
                            ).fetchone()
                            else None
                        ),
                        notes=source.get("notes"),
                        profile_name=source.get("profile_name"),
                    )
                )

            for row in payload.get("assets", []) or []:
                source = {key: self._decode_value(value) for key, value in dict(row).items()}
                self.asset_service.create_asset(
                    AssetVersionPayload(
                        asset_type=source.get("asset_type") or "other",
                        filename=source.get("filename"),
                        source_path=source.get("source_path"),
                        stored_path=source.get("stored_path"),
                        checksum_sha256=source.get("checksum_sha256"),
                        duration_sec=(
                            int(source["duration_sec"])
                            if source.get("duration_sec") not in (None, "")
                            else None
                        ),
                        sample_rate=(
                            int(source["sample_rate"])
                            if source.get("sample_rate") not in (None, "")
                            else None
                        ),
                        bit_depth=(
                            int(source["bit_depth"])
                            if source.get("bit_depth") not in (None, "")
                            else None
                        ),
                        format=source.get("format"),
                        derived_from_asset_id=None,
                        approved_for_use=bool(source.get("approved_for_use")),
                        primary_flag=bool(source.get("primary_flag")),
                        version_status=source.get("version_status"),
                        notes=source.get("notes"),
                        track_id=(
                            int(source.get("track_id"))
                            if source.get("track_id")
                            and self.conn.execute(
                                "SELECT 1 FROM Tracks WHERE id=?",
                                (int(source.get("track_id")),),
                            ).fetchone()
                            else None
                        ),
                        release_id=(
                            int(source.get("release_id"))
                            if source.get("release_id")
                            and self.conn.execute(
                                "SELECT 1 FROM Releases WHERE id=?",
                                (int(source.get("release_id")),),
                            ).fetchone()
                            else None
                        ),
                    )
                )
