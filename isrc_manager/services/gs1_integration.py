"""Facade that keeps GS1 defaults, validation, template verification, and Excel export aligned."""

from __future__ import annotations

from pathlib import Path

from isrc_manager.constants import DEFAULT_WINDOW_TITLE

from .gs1_models import (
    GS1BatchValidationError,
    GS1BatchValidationIssue,
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
            return existing, context, True
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
        prepared: list[GS1PreparedRecord] = []
        issues: list[GS1BatchValidationIssue] = []
        for track_id in track_ids:
            record, context, _ = self.load_or_create_metadata(
                track_id,
                current_profile_path=current_profile_path,
                window_title=window_title,
            )
            validation = self.validation_service.validate(record, for_export=True)
            if validation.is_valid:
                prepared.append(GS1PreparedRecord(metadata=record, context=context))
                continue
            issues.append(
                GS1BatchValidationIssue(
                    track_id=int(track_id),
                    track_label=context.display_title,
                    messages=validation.messages(),
                )
            )
        if issues:
            raise GS1BatchValidationError(issues)
        return prepared

    def export_records(
        self,
        track_ids: list[int],
        *,
        output_path: str | Path,
        template_path: str | None = None,
        current_profile_path: str = "",
        window_title: str = "",
    ):
        template_profile = self.load_template_profile(template_path)
        prepared = self.prepare_records_for_export(
            track_ids,
            current_profile_path=current_profile_path,
            window_title=window_title,
        )
        return self.excel_export_service.export(template_profile, prepared, output_path)

    @staticmethod
    def _profile_label(current_profile_path: str) -> str:
        path = Path(str(current_profile_path or "").strip())
        if not path.name:
            return ""
        stem = path.stem.strip()
        if stem.lower() in {"default", "catalog", "profile"}:
            return ""
        return stem.replace("_", " ").strip()
