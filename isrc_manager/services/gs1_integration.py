"""Facade that keeps GS1 defaults, validation, template verification, and Excel export aligned."""

from __future__ import annotations

from pathlib import Path

from isrc_manager.constants import DEFAULT_WINDOW_TITLE

from .gs1_models import (
    GS1BatchValidationError,
    GS1BatchValidationIssue,
    GS1ContractEntry,
    GS1ExportPlan,
    GS1MetadataGroup,
    GS1MetadataRecord,
    GS1PreparedRecord,
    GS1RecordContext,
    GS1TemplateProfile,
    GS1TemplateVerificationError,
    GS1ValidationError,
)
from .gs1_contracts import GS1ContractImportService
from .gs1_repository import GS1MetadataRepository
from .gs1_settings import GS1SettingsService
from .gs1_template import GS1TemplateVerificationService
from .gs1_excel import GS1ExcelExportService
from .gs1_validation import GS1ValidationService


class GS1IntegrationService:
    """Provides one stable API for the GS1 UI regardless of export transport."""

    def __init__(
        self,
        repository: GS1MetadataRepository,
        settings_service: GS1SettingsService,
        track_service,
        *,
        validation_service: GS1ValidationService | None = None,
        contract_import_service: GS1ContractImportService | None = None,
        template_verification_service: GS1TemplateVerificationService | None = None,
        excel_export_service: GS1ExcelExportService | None = None,
    ):
        self.repository = repository
        self.settings_service = settings_service
        self.track_service = track_service
        self.validation_service = validation_service or GS1ValidationService()
        self.contract_import_service = contract_import_service or GS1ContractImportService()
        self.template_verification_service = template_verification_service or GS1TemplateVerificationService()
        self.excel_export_service = excel_export_service or GS1ExcelExportService()

    def load_or_create_metadata(
        self,
        track_id: int,
        *,
        current_profile_path: str = "",
        window_title: str = "",
    ) -> tuple[GS1MetadataRecord, GS1RecordContext, bool]:
        context = self.build_context(track_id, current_profile_path=current_profile_path)
        existing = self.repository.fetch_by_track_id(track_id)
        if existing is not None:
            return self._apply_legacy_default_repairs(existing, context, window_title=window_title), context, True
        return self.build_default_metadata(track_id, current_profile_path=current_profile_path, window_title=window_title), context, False

    def build_context(self, track_id: int, *, current_profile_path: str = "") -> GS1RecordContext:
        if int(track_id) <= 0:
            raise ValueError("Could not determine the selected track.")
        snapshot = self.track_service.fetch_track_snapshot(track_id)
        if snapshot is None:
            raise ValueError(f"Track {track_id} was not found.")
        return GS1RecordContext(
            track_id=int(track_id),
            track_title=str(snapshot.track_title or "").strip(),
            album_title=str(snapshot.album_title or "").strip(),
            artist_name=str(snapshot.artist_name or "").strip(),
            upc=str(snapshot.upc or "").strip(),
            release_date=str(snapshot.release_date or "").strip(),
            catalog_number=str(snapshot.catalog_number or "").strip(),
            profile_label=self._profile_label(current_profile_path),
        )

    def build_default_metadata(
        self,
        track_id: int,
        *,
        current_profile_path: str = "",
        window_title: str = "",
    ) -> GS1MetadataRecord:
        defaults = self.settings_service.load_profile_defaults()
        context = self.build_context(track_id, current_profile_path=current_profile_path)
        product_description = context.release_title or context.track_title or f"Track {track_id}"
        profile_label = context.profile_label

        brand = defaults.brand.strip()
        if not brand:
            if profile_label:
                brand = profile_label
            elif context.artist_name:
                brand = context.artist_name
            else:
                clean_window_title = str(window_title or "").strip()
                if clean_window_title and clean_window_title != DEFAULT_WINDOW_TITLE:
                    brand = clean_window_title
        if not brand:
            brand = "UNBRANDED"

        subbrand = defaults.subbrand.strip()
        if not subbrand and defaults.brand.strip() and profile_label and profile_label != defaults.brand.strip():
            subbrand = profile_label

        return GS1MetadataRecord(
            track_id=int(track_id),
            contract_number=defaults.contract_number.strip(),
            status="Concept",
            product_classification=defaults.product_classification.strip() or "Audio",
            consumer_unit_flag=True,
            packaging_type=defaults.packaging_type.strip() or "Digital file",
            target_market=defaults.target_market.strip() or "Worldwide",
            language=defaults.language.strip() or "English",
            product_description=product_description.strip(),
            brand=brand.strip(),
            subbrand=subbrand.strip(),
            quantity="1",
            unit="Each",
            image_url="",
            notes="",
            export_enabled=True,
        )

    def load_imported_contracts(self) -> tuple[GS1ContractEntry, ...]:
        return self.settings_service.load_contracts()

    def load_contracts_csv_path(self) -> str:
        return self.settings_service.load_contracts_csv_path()

    def import_contracts_from_csv(self, csv_path: str | Path) -> tuple[GS1ContractEntry, ...]:
        contracts = self.contract_import_service.load_contracts(csv_path)
        return self.settings_service.set_contracts(contracts, source_path=str(csv_path))

    def save_metadata(self, record: GS1MetadataRecord) -> GS1MetadataRecord:
        validation = self.validation_service.validate(record, for_export=False)
        if not validation.is_valid:
            raise GS1ValidationError(validation)
        return self.repository.save(record)

    def save_metadata_group(
        self,
        group: GS1MetadataGroup,
        record: GS1MetadataRecord,
    ) -> list[GS1MetadataRecord]:
        normalized = self._normalized_group_record(group, record)
        validation = self.validation_service.validate(normalized, for_export=False)
        if not validation.is_valid:
            raise GS1ValidationError(validation)

        saved_records: list[GS1MetadataRecord] = []
        for track_id in group.track_ids:
            track_record = normalized.copy()
            track_record.id = None
            track_record.track_id = int(track_id)
            track_record.created_at = None
            track_record.updated_at = None
            saved_records.append(self.repository.save(track_record))
        return saved_records

    def validate_metadata(self, record: GS1MetadataRecord, *, for_export: bool = False):
        return self.validation_service.validate(record, for_export=for_export)

    def normalize_group_record(self, group: GS1MetadataGroup, record: GS1MetadataRecord) -> GS1MetadataRecord:
        return self._normalized_group_record(group, record)

    def validate_group_metadata(
        self,
        group: GS1MetadataGroup,
        record: GS1MetadataRecord,
        *,
        for_export: bool = False,
    ):
        return self.validation_service.validate(self._normalized_group_record(group, record), for_export=for_export)

    def load_template_profile(self, template_path: str | None = None) -> GS1TemplateProfile:
        resolved_path = str(template_path or "").strip() or self.settings_service.load_template_path()
        if not resolved_path:
            raise GS1TemplateVerificationError(
                "No GS1 workbook is configured yet. Choose the official workbook from your GS1 portal before exporting."
            )
        return self.template_verification_service.verify(resolved_path)

    def save_template_path(self, template_path: str) -> str:
        return self.settings_service.set_template_path(template_path)

    def build_metadata_groups(
        self,
        track_ids: list[int],
        *,
        current_profile_path: str = "",
        window_title: str = "",
    ) -> list[GS1MetadataGroup]:
        loaded = self._load_export_entries(
            track_ids,
            current_profile_path=current_profile_path,
            window_title=window_title,
        )
        groups: list[GS1MetadataGroup] = []
        for index, group_entries in enumerate(self._group_loaded_entries(loaded), start=1):
            representative_record, representative_context = group_entries[0]
            display_title = self._group_product_name(group_entries)
            default_record = self.build_default_metadata(
                representative_context.track_id,
                current_profile_path=current_profile_path,
                window_title=window_title,
            )
            group_record = representative_record.copy()
            group_record.product_description = display_title
            default_record.product_description = display_title
            mode = "album" if self._group_album_title(group_entries) else "single"
            groups.append(
                GS1MetadataGroup(
                    group_id=f"group_{index}",
                    tab_title=self._group_tab_title(group_entries),
                    display_title=display_title,
                    mode=mode,
                    track_ids=tuple(context.track_id for _, context in group_entries),
                    contexts=tuple(context for _, context in group_entries),
                    record=group_record,
                    default_record=default_record,
                )
            )
        return groups

    def prepare_records_for_export(
        self,
        track_ids: list[int],
        *,
        current_profile_path: str = "",
        window_title: str = "",
    ) -> list[GS1PreparedRecord]:
        groups = self.build_metadata_groups(
            track_ids,
            current_profile_path=current_profile_path,
            window_title=window_title,
        )
        if not groups:
            raise ValueError("At least one track must be selected for GS1 export.")
        issues: list[GS1BatchValidationIssue] = []
        prepared: list[GS1PreparedRecord] = []
        for group in groups:
            export_record = self._normalized_group_record(group, group.record)
            context = group.representative_context
            validation = self.validation_service.validate(export_record, for_export=True)
            if validation.is_valid:
                prepared.append(
                    GS1PreparedRecord(
                        metadata=export_record,
                        context=context,
                        source_track_ids=group.track_ids,
                        source_track_labels=tuple(self._source_track_label(entry_context) for entry_context in group.contexts),
                        source_upc_values=tuple(str(entry_context.upc or "").strip() for entry_context in group.contexts),
                    )
                )
                continue
            issues.append(
                GS1BatchValidationIssue(
                    track_id=int(context.track_id),
                    track_label=context.display_title,
                    messages=validation.messages(),
                )
            )
        if issues:
            raise GS1BatchValidationError(issues)
        return prepared

    def prepare_export_plan(
        self,
        track_ids: list[int],
        *,
        template_path: str | None = None,
        current_profile_path: str = "",
        window_title: str = "",
    ) -> GS1ExportPlan:
        template_profile = self.load_template_profile(template_path)
        prepared = self.prepare_records_for_export(
            track_ids,
            current_profile_path=current_profile_path,
            window_title=window_title,
        )
        preview = self.excel_export_service.build_preview(template_profile, prepared)
        records_by_sheet = self._records_by_sheet(template_profile, prepared)
        summary_lines = self._build_export_summary(
            track_ids=track_ids,
            prepared_records=prepared,
            template_profile=template_profile,
            records_by_sheet=records_by_sheet,
        )
        warnings = self._build_upc_warnings(prepared)
        return GS1ExportPlan(
            template_profile=template_profile,
            prepared_records=tuple(prepared),
            preview=preview,
            warnings=tuple(warnings),
            summary_lines=tuple(summary_lines),
            mode=self._export_mode(prepared),
        )

    def export_plan(
        self,
        plan: GS1ExportPlan,
        *,
        output_path: str | Path,
    ):
        return self.excel_export_service.export(
            plan.template_profile,
            list(plan.prepared_records),
            output_path,
        )

    def export_records(
        self,
        track_ids: list[int],
        *,
        output_path: str | Path,
        template_path: str | None = None,
        current_profile_path: str = "",
        window_title: str = "",
    ):
        plan = self.prepare_export_plan(
            track_ids,
            template_path=template_path,
            current_profile_path=current_profile_path,
            window_title=window_title,
        )
        return self.export_plan(plan, output_path=output_path)

    @staticmethod
    def _profile_label(current_profile_path: str) -> str:
        path = Path(str(current_profile_path or "").strip())
        if not path.name:
            return ""
        stem = path.stem.strip()
        if stem.lower() in {"default", "catalog", "profile"}:
            return ""
        return stem.replace("_", " ").strip()

    def _apply_legacy_default_repairs(
        self,
        record: GS1MetadataRecord,
        context: GS1RecordContext,
        *,
        window_title: str,
    ) -> GS1MetadataRecord:
        defaults = self.settings_service.load_profile_defaults()
        default_contract_number = defaults.contract_number.strip()
        default_brand = defaults.brand.strip()
        default_subbrand = defaults.subbrand.strip()
        if not default_contract_number and not default_brand and not default_subbrand:
            return record

        profile_label = context.profile_label.strip()
        artist_name = context.artist_name.strip()
        clean_window_title = str(window_title or "").strip()
        if clean_window_title == DEFAULT_WINDOW_TITLE:
            clean_window_title = ""

        legacy_candidates = {
            self._normalize_identity_value(value)
            for value in (profile_label, artist_name, clean_window_title, "UNBRANDED")
            if value
        }
        current_brand_key = self._normalize_identity_value(record.brand)
        current_subbrand_key = self._normalize_identity_value(record.subbrand)
        default_brand_key = self._normalize_identity_value(default_brand)
        default_subbrand_key = self._normalize_identity_value(default_subbrand)

        repaired = record.copy()
        if default_contract_number and not repaired.contract_number.strip():
            repaired.contract_number = default_contract_number
        brand_looks_legacy = bool(current_brand_key) and current_brand_key in legacy_candidates

        if default_brand and (not current_brand_key or brand_looks_legacy):
            repaired.brand = default_brand
            current_brand_key = default_brand_key

        if default_subbrand and not current_subbrand_key:
            if brand_looks_legacy or (default_brand_key and current_brand_key == default_brand_key):
                repaired.subbrand = default_subbrand

        return repaired

    @staticmethod
    def _normalize_identity_value(value: str) -> str:
        return "".join(ch.lower() for ch in str(value or "").strip() if ch.isalnum())

    def _load_export_entries(
        self,
        track_ids: list[int],
        *,
        current_profile_path: str,
        window_title: str,
    ) -> list[tuple[GS1MetadataRecord, GS1RecordContext]]:
        normalized_ids: list[int] = []
        seen: set[int] = set()
        for track_id in track_ids:
            try:
                clean_id = int(track_id)
            except (TypeError, ValueError):
                continue
            if clean_id <= 0 or clean_id in seen:
                continue
            seen.add(clean_id)
            normalized_ids.append(clean_id)

        loaded: list[tuple[GS1MetadataRecord, GS1RecordContext]] = []
        for track_id in normalized_ids:
            record, context, _ = self.load_or_create_metadata(
                track_id,
                current_profile_path=current_profile_path,
                window_title=window_title,
            )
            loaded.append((record, context))
        return loaded

    @staticmethod
    def _source_track_label(context: GS1RecordContext) -> str:
        title = str(context.track_title or "").strip() or f"Track {context.track_id}"
        effective_album_title = GS1IntegrationService._effective_album_title(context.album_title)
        if effective_album_title and effective_album_title != title:
            return f"{title} ({effective_album_title})"
        return title

    @staticmethod
    def _single_product_name(track_title: str, track_id: int) -> str:
        clean_title = str(track_title or "").strip() or f"Track {track_id}"
        if clean_title.lower().endswith(" - single"):
            return clean_title
        return f"{clean_title} - Single"

    @staticmethod
    def _export_mode(prepared: list[GS1PreparedRecord]) -> str:
        if not prepared:
            return "single"
        album_groups = sum(
            1
            for record in prepared
            if len(record.source_track_ids) > 1 or GS1IntegrationService._effective_album_title(record.context.album_title)
        )
        single_groups = sum(
            1
            for record in prepared
            if not GS1IntegrationService._effective_album_title(record.context.album_title)
        )
        if len(prepared) == 1 and album_groups == 1:
            return "album"
        if album_groups and single_groups:
            return "mixed_groups"
        if album_groups and len(prepared) > 1:
            return "album_groups"
        if single_groups and len(prepared) > 1:
            return "single_groups"
        return "single"

    def _build_export_summary(
        self,
        *,
        track_ids: list[int],
        prepared_records: list[GS1PreparedRecord],
        template_profile: GS1TemplateProfile,
        records_by_sheet: dict[str, list[GS1PreparedRecord]],
    ) -> list[str]:
        sheet_names = list(records_by_sheet)
        if len(sheet_names) == 1:
            destination_text = f"into '{sheet_names[0]}'"
        else:
            destination_text = f"across {len(sheet_names)} contract sheets"
        lines = [
            f"This export will write {len(prepared_records)} GS1 product row(s) from {len(track_ids)} selected track(s) {destination_text}.",
        ]
        if len(sheet_names) == 1:
            lines.append("The GS1 request/code field will be filled with 1, 2, 3, ... in export order.")
        else:
            lines.append(
                "The GS1 request/code field restarts at 1 on each contract sheet, so every selected contract receives its own 1, 2, 3, ... sequence."
            )
            for sheet_name, records in records_by_sheet.items():
                lines.append(f"Sheet '{sheet_name}': {len(records)} product row(s).")
        if not prepared_records:
            return lines
        album_titles = [
            record.metadata.product_description.strip()
            for record in prepared_records
            if self._effective_album_title(record.context.album_title)
        ]
        single_count = sum(1 for record in prepared_records if not self._effective_album_title(record.context.album_title))
        if album_titles:
            lines.insert(
                1,
                "Tracks with a non-empty album title are grouped into one GS1 product row per album title.",
            )
        if single_count:
            lines.insert(
                2 if album_titles else 1,
                "Tracks without an album title are exported as individual single rows so each single can receive its own UPC/GTIN assignment.",
            )
        if len(prepared_records) == 1:
            lines.insert(
                1,
                f"Single-product export for '{prepared_records[0].metadata.product_description.strip() or prepared_records[0].context.display_title}'.",
            )
        return lines

    @staticmethod
    def _records_by_sheet(
        template_profile: GS1TemplateProfile,
        prepared_records: list[GS1PreparedRecord],
    ) -> dict[str, list[GS1PreparedRecord]]:
        grouped: dict[str, list[GS1PreparedRecord]] = {}
        for prepared in prepared_records:
            sheet_name = template_profile.resolve_sheet_name(prepared.metadata.contract_number)
            grouped.setdefault(sheet_name, []).append(prepared)
        return grouped

    @staticmethod
    def _build_upc_warnings(prepared_records: list[GS1PreparedRecord]) -> list[str]:
        upc_details: list[str] = []
        unique_upcs: list[str] = []
        seen_upcs: set[str] = set()
        for prepared in prepared_records:
            source_labels = prepared.source_track_labels or (GS1IntegrationService._source_track_label(prepared.context),)
            source_upcs = prepared.source_upc_values or (str(prepared.context.upc or "").strip(),)
            for index, track_label in enumerate(source_labels):
                upc_value = str(source_upcs[index] if index < len(source_upcs) else "").strip()
                if not upc_value:
                    continue
                upc_details.append(f"{track_label}: {upc_value}")
                if upc_value not in seen_upcs:
                    seen_upcs.add(upc_value)
                    unique_upcs.append(upc_value)

        if not upc_details:
            return []

        warnings = [
            "One or more selected tracks already have a UPC/EAN stored. Review this carefully because only one UPC/EAN should be assigned per registered GS1 product.",
            "Existing UPC/EAN values: " + "; ".join(upc_details),
        ]
        if len(unique_upcs) > 1:
            warnings.append(
                "Multiple different UPC/EAN values are present in the selection. Confirm that the export grouping matches the product you want to register."
            )
        return warnings

    def _normalized_group_record(self, group: GS1MetadataGroup, record: GS1MetadataRecord) -> GS1MetadataRecord:
        normalized = record.copy()
        normalized.track_id = int(group.representative_context.track_id)
        normalized.product_description = group.display_title
        return normalized

    def _group_loaded_entries(
        self,
        loaded: list[tuple[GS1MetadataRecord, GS1RecordContext]],
    ) -> list[list[tuple[GS1MetadataRecord, GS1RecordContext]]]:
        grouped: list[list[tuple[GS1MetadataRecord, GS1RecordContext]]] = []
        index_by_key: dict[str, int] = {}
        for record, context in loaded:
            album_title = self._effective_album_title(context.album_title)
            if album_title:
                group_key = f"album::{album_title.casefold()}"
            else:
                group_key = f"track::{int(context.track_id)}"
            group_index = index_by_key.get(group_key)
            if group_index is None:
                index_by_key[group_key] = len(grouped)
                grouped.append([(record, context)])
                continue
            grouped[group_index].append((record, context))
        return grouped

    def _group_product_name(
        self,
        group_entries: list[tuple[GS1MetadataRecord, GS1RecordContext]],
    ) -> str:
        album_title = self._group_album_title(group_entries)
        if album_title:
            return album_title
        _, context = group_entries[0]
        return self._single_product_name(context.track_title, context.track_id)

    def _group_tab_title(
        self,
        group_entries: list[tuple[GS1MetadataRecord, GS1RecordContext]],
    ) -> str:
        album_title = self._group_album_title(group_entries)
        if album_title:
            if len(group_entries) > 1:
                return f"{album_title} ({len(group_entries)})"
            return album_title
        _, context = group_entries[0]
        return str(context.track_title or "").strip() or f"Track {context.track_id}"

    @staticmethod
    def _group_album_title(
        group_entries: list[tuple[GS1MetadataRecord, GS1RecordContext]],
    ) -> str:
        if not group_entries:
            return ""
        return GS1IntegrationService._effective_album_title(group_entries[0][1].album_title)

    @staticmethod
    def _effective_album_title(album_title: str | None) -> str:
        clean_title = str(album_title or "").strip()
        if clean_title.lower() == "single":
            return ""
        return clean_title
