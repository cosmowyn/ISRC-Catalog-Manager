"""Facade that keeps GS1 defaults, validation, template verification, and Excel export aligned."""

from __future__ import annotations

from pathlib import Path

from isrc_manager.constants import DEFAULT_WINDOW_TITLE

from .gs1_models import (
    GS1BatchValidationError,
    GS1BatchValidationIssue,
    GS1ExportPlan,
    GS1MetadataRecord,
    GS1PreparedRecord,
    GS1RecordContext,
    GS1TemplateProfile,
    GS1TemplateVerificationError,
    GS1ValidationError,
)
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
        template_verification_service: GS1TemplateVerificationService | None = None,
        excel_export_service: GS1ExcelExportService | None = None,
    ):
        self.repository = repository
        self.settings_service = settings_service
        self.track_service = track_service
        self.validation_service = validation_service or GS1ValidationService()
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

    def save_metadata(self, record: GS1MetadataRecord) -> GS1MetadataRecord:
        validation = self.validation_service.validate(record, for_export=False)
        if not validation.is_valid:
            raise GS1ValidationError(validation)
        return self.repository.save(record)

    def validate_metadata(self, record: GS1MetadataRecord, *, for_export: bool = False):
        return self.validation_service.validate(record, for_export=for_export)

    def load_template_profile(self, template_path: str | None = None) -> GS1TemplateProfile:
        resolved_path = str(template_path or "").strip() or self.settings_service.load_template_path()
        if not resolved_path:
            raise GS1TemplateVerificationError(
                "No GS1 workbook is configured yet. Choose the official workbook from your GS1 portal before exporting."
            )
        return self.template_verification_service.verify(resolved_path)

    def save_template_path(self, template_path: str) -> str:
        return self.settings_service.set_template_path(template_path)

    def prepare_records_for_export(
        self,
        track_ids: list[int],
        *,
        current_profile_path: str = "",
        window_title: str = "",
    ) -> list[GS1PreparedRecord]:
        loaded = self._load_export_entries(
            track_ids,
            current_profile_path=current_profile_path,
            window_title=window_title,
        )
        if not loaded:
            raise ValueError("At least one track must be selected for GS1 export.")

        shared_album_title = self._shared_album_title([context for _, context in loaded])
        issues: list[GS1BatchValidationIssue] = []

        if len(loaded) > 1 and shared_album_title:
            representative_record, representative_context = loaded[0]
            grouped_record = representative_record.copy()
            grouped_record.product_description = shared_album_title
            validation = self.validation_service.validate(grouped_record, for_export=True)
            if not validation.is_valid:
                raise GS1BatchValidationError(
                    [
                        GS1BatchValidationIssue(
                            track_id=int(representative_context.track_id),
                            track_label=representative_context.display_title,
                            messages=validation.messages(),
                        )
                    ]
                )
            return [
                GS1PreparedRecord(
                    metadata=grouped_record,
                    context=representative_context,
                    source_track_ids=tuple(context.track_id for _, context in loaded),
                    source_track_labels=tuple(self._source_track_label(context) for _, context in loaded),
                    source_upc_values=tuple(str(context.upc or "").strip() for _, context in loaded),
                )
            ]

        prepared: list[GS1PreparedRecord] = []
        for record, context in loaded:
            export_record = record.copy()
            if len(loaded) > 1:
                export_record.product_description = self._single_product_name(context.track_title, context.track_id)
            validation = self.validation_service.validate(export_record, for_export=True)
            if validation.is_valid:
                prepared.append(
                    GS1PreparedRecord(
                        metadata=export_record,
                        context=context,
                        source_track_ids=(context.track_id,),
                        source_track_labels=(self._source_track_label(context),),
                        source_upc_values=(str(context.upc or "").strip(),),
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
        mode = self._export_mode(prepared, track_ids)
        summary_lines = self._build_export_summary(
            mode=mode,
            track_ids=track_ids,
            prepared_records=prepared,
            template_profile=template_profile,
        )
        warnings = self._build_upc_warnings(prepared)
        return GS1ExportPlan(
            template_profile=template_profile,
            prepared_records=tuple(prepared),
            preview=preview,
            warnings=tuple(warnings),
            summary_lines=tuple(summary_lines),
            mode=mode,
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
        default_brand = defaults.brand.strip()
        default_subbrand = defaults.subbrand.strip()
        if not default_brand and not default_subbrand:
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
    def _shared_album_title(contexts: list[GS1RecordContext]) -> str:
        album_titles = {str(context.album_title or "").strip() for context in contexts}
        if len(album_titles) != 1:
            return ""
        shared_title = next(iter(album_titles)).strip()
        return shared_title if shared_title else ""

    @staticmethod
    def _source_track_label(context: GS1RecordContext) -> str:
        title = str(context.track_title or "").strip() or f"Track {context.track_id}"
        if context.album_title and context.album_title.strip() != title:
            return f"{title} ({context.album_title.strip()})"
        return title

    @staticmethod
    def _single_product_name(track_title: str, track_id: int) -> str:
        clean_title = str(track_title or "").strip() or f"Track {track_id}"
        if clean_title.lower().endswith(" - single"):
            return clean_title
        return f"{clean_title} - Single"

    @staticmethod
    def _export_mode(prepared: list[GS1PreparedRecord], track_ids: list[int]) -> str:
        if len(prepared) == 1 and len(track_ids) > 1 and len(prepared[0].source_track_ids) > 1:
            return "shared_album"
        if len(prepared) > 1 and len(track_ids) > 1:
            return "separate_singles"
        return "single"

    def _build_export_summary(
        self,
        *,
        mode: str,
        track_ids: list[int],
        prepared_records: list[GS1PreparedRecord],
        template_profile: GS1TemplateProfile,
    ) -> list[str]:
        lines = [
            f"This export will write {len(prepared_records)} GS1 product row(s) into '{template_profile.sheet_name}'.",
            "The GS1 request/code field will be filled with 1, 2, 3, ... in export order.",
        ]
        if not prepared_records:
            return lines
        if mode == "shared_album":
            album_title = prepared_records[0].metadata.product_description.strip() or prepared_records[0].context.display_title
            lines.insert(
                1,
                f"All {len(prepared_records[0].source_track_ids)} selected tracks share album '{album_title}', so they will be exported as one GS1 product.",
            )
            return lines
        if mode == "separate_singles":
            lines.insert(
                1,
                "Selected tracks do not all share one album title, so each track will be exported as a separate GS1 product named 'Track Title - Single'.",
            )
            return lines
        lines.insert(
            1,
            f"Single-product export for '{prepared_records[0].metadata.product_description.strip() or prepared_records[0].context.display_title}'.",
        )
        return lines

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
