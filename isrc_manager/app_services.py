"""Foreground/UI-thread service wiring for the main application window."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from isrc_manager.assets import AssetService
from isrc_manager.authenticity import (
    AUTHENTICITY_FEATURE_AVAILABLE,
    AudioAuthenticityService,
    AudioWatermarkService,
    AuthenticityKeyService,
    AuthenticityManifestService,
)
from isrc_manager.blob_icons import BlobIconSettingsService
from isrc_manager.contract_templates import ContractTemplateService
from isrc_manager.contract_templates.catalog import ContractTemplateCatalogService
from isrc_manager.contract_templates.export_service import ContractTemplateExportService
from isrc_manager.contract_templates.form_service import ContractTemplateFormService
from isrc_manager.contracts import ContractService
from isrc_manager.conversion import ConversionService, ConversionTemplateStoreService
from isrc_manager.exchange.repertoire_service import RepertoireExchangeService
from isrc_manager.exchange.service import ExchangeService
from isrc_manager.forensics import ForensicExportCoordinator, ForensicWatermarkService
from isrc_manager.history import HistoryManager, HistoryStorageCleanupService
from isrc_manager.media import AudioConversionService
from isrc_manager.parties import PartyExchangeService, PartyService
from isrc_manager.promo_codes import PromoCodeService
from isrc_manager.quality.service import QualityDashboardService
from isrc_manager.releases import ReleaseService
from isrc_manager.rights import RightsService
from isrc_manager.search import GlobalSearchService, RelationshipExplorerService
from isrc_manager.services import (
    ApplicationSettingsTransferService,
    CatalogAdminService,
    CatalogReadService,
    CodeRegistryService,
    CustomFieldDefinitionService,
    CustomFieldValueService,
    DatabaseSchemaService,
    GS1IntegrationService,
    GS1MetadataRepository,
    GS1SettingsService,
    ProfileKVService,
    RepertoireWorkflowService,
    SettingsMutationService,
    SettingsReadService,
    TrackImportRepairQueueService,
    TrackService,
    WorkService,
    XMLExportService,
    XMLImportService,
)
from isrc_manager.services.import_governance import GovernedImportCoordinator
from isrc_manager.tags import AudioTagService, TaggedAudioExportService


def initialize_foreground_services(app: Any) -> None:
    app.schema_service = (
        DatabaseSchemaService(
            app.conn,
            logger=app.logger,
            audit_callback=app._audit,
            audit_commit=app._audit_commit,
            data_root=app.data_root,
        )
        if app.conn is not None
        else None
    )
    app.history_manager = (
        HistoryManager(
            app.conn,
            app.settings,
            app.current_db_path,
            app.history_dir,
            app.data_root,
            app.backups_dir,
        )
        if app.conn is not None and getattr(app, "current_db_path", None)
        else None
    )
    app.history_cleanup_service = (
        HistoryStorageCleanupService(app.history_manager)
        if app.history_manager is not None
        else None
    )
    app.track_service = (
        TrackService(
            app.conn,
            app.data_root,
            require_governed_creation=True,
        )
        if app.conn is not None
        else None
    )
    if app.track_service is not None:
        app.track_service.waveform_cache_scheduler = app._queue_audio_waveform_cache_for_track
    app.settings_reads = SettingsReadService(app.conn) if app.conn is not None else None
    app.settings_mutations = (
        SettingsMutationService(app.conn, app.settings) if app.conn is not None else None
    )
    app.blob_icon_settings_service = (
        BlobIconSettingsService(app.conn) if app.conn is not None else None
    )
    app.gs1_settings_service = (
        GS1SettingsService(app.conn, app.settings, data_root=app.data_root)
        if app.conn is not None
        else None
    )
    app.settings_transfer_service = (
        ApplicationSettingsTransferService(
            gs1_settings_service=app.gs1_settings_service,
            data_root=app.data_root,
        )
        if app.conn is not None
        else None
    )
    app.catalog_service = CatalogAdminService(app.conn) if app.conn is not None else None
    app.catalog_reads = CatalogReadService(app.conn) if app.conn is not None else None
    app.code_registry_service = CodeRegistryService(app.conn) if app.conn is not None else None
    app.promo_code_service = PromoCodeService(app.conn) if app.conn is not None else None
    app.profile_kv = ProfileKVService(app.conn) if app.conn is not None else None
    app.track_import_repair_queue_service = (
        TrackImportRepairQueueService(app.conn) if app.conn is not None else None
    )
    app.custom_field_definitions = (
        CustomFieldDefinitionService(app.conn) if app.conn is not None else None
    )
    app.contract_template_catalog_service = (
        ContractTemplateCatalogService(
            app.conn,
            custom_field_definition_service=app.custom_field_definitions,
        )
        if app.conn is not None
        else None
    )
    app.contract_template_service = (
        ContractTemplateService(app.conn, app.data_root) if app.conn is not None else None
    )
    app.custom_field_values = (
        CustomFieldValueService(app.conn, app.custom_field_definitions, app.data_root)
        if app.conn is not None
        else None
    )
    app.xml_export_service = XMLExportService(app.conn) if app.conn is not None else None
    app.xml_import_service = (
        XMLImportService(app.conn, app.track_service, app.custom_field_definitions)
        if app.conn is not None
        else None
    )
    app.release_service = ReleaseService(app.conn, app.data_root) if app.conn is not None else None
    app.party_service = PartyService(app.conn) if app.conn is not None else None
    app.work_service = (
        WorkService(app.conn, party_service=app.party_service) if app.conn is not None else None
    )
    app.governed_track_creation_service = (
        GovernedImportCoordinator(
            app.conn,
            track_service=app.track_service,
            party_service=app.party_service,
            work_service=app.work_service,
            profile_name=app._current_profile_name(),
        )
        if app.conn is not None and app.track_service is not None
        else None
    )
    app.xml_import_service = (
        XMLImportService(
            app.conn,
            app.track_service,
            app.custom_field_definitions,
            party_service=app.party_service,
            work_service=app.work_service,
            profile_name=app._current_profile_name(),
            repair_queue_service=app.track_import_repair_queue_service,
        )
        if (
            app.conn is not None
            and app.track_service is not None
            and app.custom_field_definitions is not None
        )
        else None
    )
    app.contract_service = (
        ContractService(app.conn, app.data_root, party_service=app.party_service)
        if app.conn is not None
        else None
    )
    app.rights_service = RightsService(app.conn) if app.conn is not None else None
    app.asset_service = AssetService(app.conn, app.data_root) if app.conn is not None else None
    app.contract_template_form_service = (
        ContractTemplateFormService(
            template_service=app.contract_template_service,
            catalog_service=app.contract_template_catalog_service,
            settings_reads=app.settings_reads,
            release_service=app.release_service,
            work_service=app.work_service,
            contract_service=app.contract_service,
            party_service=app.party_service,
            rights_service=app.rights_service,
            asset_service=app.asset_service,
        )
        if app.contract_template_service is not None
        and app.contract_template_catalog_service is not None
        else None
    )
    app.contract_template_export_service = (
        ContractTemplateExportService(
            template_service=app.contract_template_service,
            catalog_service=app.contract_template_catalog_service,
            settings_reads=app.settings_reads,
            track_service=app.track_service,
            release_service=app.release_service,
            work_service=app.work_service,
            contract_service=app.contract_service,
            party_service=app.party_service,
            rights_service=app.rights_service,
            asset_service=app.asset_service,
            custom_field_definition_service=app.custom_field_definitions,
            custom_field_value_service=app.custom_field_values,
        )
        if app.contract_template_service is not None
        and app.contract_template_catalog_service is not None
        else None
    )
    app.authenticity_key_service = (
        AuthenticityKeyService(
            app.conn,
            profile_kv=app.profile_kv,
            settings_root=Path(app.settings.fileName()).resolve().parent,
        )
        if app.conn is not None
        and app.profile_kv is not None
        and AUTHENTICITY_FEATURE_AVAILABLE
        and AuthenticityKeyService is not None
        else None
    )
    app.authenticity_manifest_service = (
        AuthenticityManifestService(
            app.conn,
            track_service=app.track_service,
            release_service=app.release_service,
            work_service=app.work_service,
            rights_service=app.rights_service,
            asset_service=app.asset_service,
            key_service=app.authenticity_key_service,
        )
        if app.conn is not None
        and app.track_service is not None
        and app.release_service is not None
        and app.work_service is not None
        and app.rights_service is not None
        and app.asset_service is not None
        and app.authenticity_key_service is not None
        and AUTHENTICITY_FEATURE_AVAILABLE
        and AuthenticityManifestService is not None
        else None
    )
    app.audio_watermark_service = (
        AudioWatermarkService()
        if app.conn is not None
        and AUTHENTICITY_FEATURE_AVAILABLE
        and AudioWatermarkService is not None
        else None
    )
    app.audio_conversion_service = AudioConversionService()
    app.audio_tag_service = AudioTagService() if app.conn is not None else None
    app.audio_authenticity_service = (
        AudioAuthenticityService(
            app.conn,
            key_service=app.authenticity_key_service,
            manifest_service=app.authenticity_manifest_service,
            watermark_service=app.audio_watermark_service,
            tag_service=app.audio_tag_service,
            app_version=app._app_version_text(),
        )
        if app.conn is not None
        and app.authenticity_key_service is not None
        and app.authenticity_manifest_service is not None
        and app.audio_watermark_service is not None
        and app.audio_tag_service is not None
        and AUTHENTICITY_FEATURE_AVAILABLE
        and AudioAuthenticityService is not None
        else None
    )
    app.forensic_watermark_service = (
        ForensicWatermarkService()
        if app.conn is not None
        and app.authenticity_key_service is not None
        and ForensicWatermarkService is not None
        else None
    )
    app.forensic_export_service = (
        ForensicExportCoordinator(
            conn=app.conn,
            track_service=app.track_service,
            release_service=app.release_service,
            tag_service=app.audio_tag_service,
            key_service=app.authenticity_key_service,
            conversion_service=app.audio_conversion_service,
            watermark_service=app.forensic_watermark_service,
        )
        if app.conn is not None
        and app.track_service is not None
        and app.audio_tag_service is not None
        and app.authenticity_key_service is not None
        and app.audio_conversion_service is not None
        and app.forensic_watermark_service is not None
        and ForensicExportCoordinator is not None
        else None
    )
    app.repertoire_workflow_service = (
        RepertoireWorkflowService(app.conn) if app.conn is not None else None
    )
    app.global_search_service = GlobalSearchService(app.conn) if app.conn is not None else None
    app._refresh_audio_conversion_action_states()


def configure_foreground_exchange_services(app: Any) -> None:
    app.relationship_explorer_service = (
        RelationshipExplorerService(app.conn) if app.conn is not None else None
    )
    app.tagged_audio_export_service = (
        TaggedAudioExportService(app.audio_tag_service)
        if app.audio_tag_service is not None
        else None
    )
    app.exchange_service = (
        ExchangeService(
            app.conn,
            app.track_service,
            app.release_service,
            app.custom_field_definitions,
            app.data_root,
            party_service=app.party_service,
            work_service=app.work_service,
            profile_name=app._current_profile_name(),
            repair_queue_service=app.track_import_repair_queue_service,
        )
        if (
            app.conn is not None
            and app.track_service is not None
            and app.release_service is not None
            and app.custom_field_definitions is not None
        )
        else None
    )
    app.conversion_service = ConversionService(
        exchange_service=app.exchange_service,
        settings_read_service=app.settings_reads,
    )
    app.conversion_template_store_service = (
        ConversionTemplateStoreService(app.conn) if app.conn is not None else None
    )
    app.party_exchange_service = (
        PartyExchangeService(
            app.conn,
            party_service=app.party_service,
            settings_mutations=app.settings_mutations,
            profile_name=app._current_profile_name(),
        )
        if app.conn is not None and app.party_service is not None
        else None
    )
    app.repertoire_exchange_service = (
        RepertoireExchangeService(
            app.conn,
            party_service=app.party_service,
            work_service=app.work_service,
            contract_service=app.contract_service,
            rights_service=app.rights_service,
            asset_service=app.asset_service,
            data_root=app.data_root,
        )
        if (
            app.conn is not None
            and app.party_service is not None
            and app.work_service is not None
            and app.contract_service is not None
            and app.rights_service is not None
            and app.asset_service is not None
        )
        else None
    )
    app.quality_service = (
        QualityDashboardService(
            app.conn,
            track_service=app.track_service,
            release_service=app.release_service,
            data_root=app.data_root,
        )
        if app.conn is not None
        and app.track_service is not None
        and app.release_service is not None
        else None
    )
    app.gs1_integration_service = (
        GS1IntegrationService(
            GS1MetadataRepository(app.conn),
            app.gs1_settings_service,
            app.track_service,
        )
        if app.conn is not None
        and app.gs1_settings_service is not None
        and app.track_service is not None
        else None
    )


__all__ = ["configure_foreground_exchange_services", "initialize_foreground_services"]
