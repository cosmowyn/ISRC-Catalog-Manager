"""Factories for recreating app service bundles inside worker threads."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from importlib import metadata
from pathlib import Path

from PySide6.QtCore import QSettings

from isrc_manager.assets import AssetService
from isrc_manager.authenticity import (
    AUTHENTICITY_FEATURE_AVAILABLE,
    AudioAuthenticityService,
    AudioWatermarkService,
    AuthenticityKeyService,
    AuthenticityManifestService,
)
from isrc_manager.contracts import ContractService
from isrc_manager.contract_templates import ContractTemplateService
from isrc_manager.exchange import MasterTransferService
from isrc_manager.exchange.repertoire_service import RepertoireExchangeService
from isrc_manager.exchange.service import ExchangeService
from isrc_manager.forensics import ForensicExportCoordinator, ForensicWatermarkService
from isrc_manager.history import HistoryManager
from isrc_manager.media import AudioConversionService
from isrc_manager.parties import PartyExchangeService, PartyService
from isrc_manager.quality.service import QualityDashboardService
from isrc_manager.releases import ReleaseService
from isrc_manager.rights import RightsService
from isrc_manager.search import GlobalSearchService, RelationshipExplorerService
from isrc_manager.services import (
    CatalogReadService,
    CustomFieldDefinitionService,
    CustomFieldValueService,
    DatabaseMaintenanceService,
    GS1IntegrationService,
    GS1MetadataRepository,
    GS1SettingsService,
    LegacyLicenseMigrationService,
    LicenseService,
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
from isrc_manager.services.db_access import SQLiteConnectionFactory
from isrc_manager.tags import AudioTagService, TaggedAudioExportService


def _app_version_text() -> str:
    for package_name in ("isrc-catalog-manager", "ISRC Catalog Manager"):
        try:
            return metadata.version(package_name)
        except metadata.PackageNotFoundError:
            continue
        except Exception:
            break
    return "3.1.0"


@dataclass(slots=True)
class BackgroundAppServiceBundle:
    conn: sqlite3.Connection
    settings: QSettings
    track_service: TrackService
    release_service: ReleaseService
    license_service: LicenseService
    catalog_reads: CatalogReadService
    custom_field_definitions: CustomFieldDefinitionService
    custom_field_values: CustomFieldValueService
    xml_export_service: XMLExportService
    xml_import_service: XMLImportService
    exchange_service: ExchangeService
    repertoire_exchange_service: RepertoireExchangeService
    party_exchange_service: PartyExchangeService
    master_transfer_service: MasterTransferService
    quality_service: QualityDashboardService
    party_service: PartyService
    work_service: WorkService
    contract_service: ContractService
    license_migration_service: LegacyLicenseMigrationService
    rights_service: RightsService
    asset_service: AssetService
    workflow_service: RepertoireWorkflowService
    global_search_service: GlobalSearchService
    relationship_explorer_service: RelationshipExplorerService
    gs1_settings_service: GS1SettingsService
    gs1_integration_service: GS1IntegrationService
    audio_tag_service: AudioTagService
    tagged_audio_export_service: TaggedAudioExportService
    track_import_repair_queue: TrackImportRepairQueueService
    history_manager: HistoryManager
    database_maintenance: DatabaseMaintenanceService
    settings_reads: SettingsReadService
    settings_mutations: SettingsMutationService
    profile_kv: ProfileKVService
    authenticity_key_service: AuthenticityKeyService
    authenticity_manifest_service: AuthenticityManifestService
    audio_watermark_service: AudioWatermarkService
    audio_authenticity_service: AudioAuthenticityService
    forensic_watermark_service: ForensicWatermarkService
    forensic_export_service: ForensicExportCoordinator

    def close(self) -> None:
        try:
            self.settings.sync()
        except Exception:
            pass
        try:
            if self.conn.in_transaction:
                self.conn.commit()
        except Exception:
            pass
        try:
            self.conn.close()
        except Exception:
            pass

    def __enter__(self) -> "BackgroundAppServiceBundle":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if exc_type is not None:
            try:
                if self.conn.in_transaction:
                    self.conn.rollback()
            except Exception:
                pass
        self.close()


class BackgroundAppServiceFactory:
    """Rebuilds profile-scoped service objects on a worker-thread connection."""

    def __init__(
        self,
        *,
        connection_factory: SQLiteConnectionFactory,
        data_root: str | Path,
        history_dir: str | Path,
        backups_dir: str | Path,
        settings_path: str | Path | None = None,
        db_path: str | Path | None = None,
    ):
        self.connection_factory = connection_factory
        self.data_root = Path(data_root)
        self.history_dir = Path(history_dir)
        self.backups_dir = Path(backups_dir)
        self.settings_path = str(settings_path) if settings_path else None
        self.db_path = str(db_path) if db_path else None

    def configure(
        self,
        *,
        db_path: str | Path | None = None,
        settings_path: str | Path | None = None,
        data_root: str | Path | None = None,
        history_dir: str | Path | None = None,
        backups_dir: str | Path | None = None,
    ) -> None:
        if db_path is not None:
            self.db_path = str(db_path)
        if settings_path is not None:
            self.settings_path = str(settings_path)
        if data_root is not None:
            self.data_root = Path(data_root)
        if history_dir is not None:
            self.history_dir = Path(history_dir)
        if backups_dir is not None:
            self.backups_dir = Path(backups_dir)

    def open_bundle(self) -> BackgroundAppServiceBundle:
        if not self.db_path:
            raise ValueError("No profile database is currently open.")
        if not self.settings_path:
            raise ValueError("No settings file path is available for background services.")

        settings = QSettings(str(self.settings_path), QSettings.IniFormat)
        settings.setFallbacksEnabled(False)
        conn = self.connection_factory.open(self.db_path)

        track_service = TrackService(
            conn,
            self.data_root,
            require_governed_creation=True,
        )
        release_service = ReleaseService(conn, self.data_root)
        license_service = LicenseService(conn, self.data_root)
        custom_field_definitions = CustomFieldDefinitionService(conn)
        custom_field_values = CustomFieldValueService(
            conn,
            custom_field_definitions,
            self.data_root,
        )
        catalog_reads = CatalogReadService(conn)
        settings_reads = SettingsReadService(conn)
        settings_mutations = SettingsMutationService(conn, settings)
        gs1_settings_service = GS1SettingsService(conn, settings, data_root=self.data_root)
        audio_tag_service = AudioTagService()
        party_service = PartyService(conn)
        work_service = WorkService(conn, party_service=party_service)
        contract_service = ContractService(conn, self.data_root, party_service=party_service)
        contract_template_service = ContractTemplateService(conn, self.data_root)
        license_migration_service = LegacyLicenseMigrationService(
            conn,
            license_service=license_service,
            party_service=party_service,
            contract_service=contract_service,
            release_service=release_service,
            work_service=work_service,
        )
        rights_service = RightsService(conn)
        asset_service = AssetService(conn, self.data_root)
        workflow_service = RepertoireWorkflowService(conn)
        global_search_service = GlobalSearchService(conn)
        relationship_explorer_service = RelationshipExplorerService(conn)
        profile_kv = ProfileKVService(conn)
        track_import_repair_queue = TrackImportRepairQueueService(conn)
        xml_export_service = XMLExportService(conn)
        xml_import_service = XMLImportService(
            conn,
            track_service,
            custom_field_definitions,
            party_service=party_service,
            work_service=work_service,
            profile_name=Path(self.db_path).name,
            repair_queue_service=track_import_repair_queue,
        )
        exchange_service = ExchangeService(
            conn,
            track_service,
            release_service,
            custom_field_definitions,
            self.data_root,
            party_service=party_service,
            work_service=work_service,
            profile_name=Path(self.db_path).name,
            repair_queue_service=track_import_repair_queue,
        )
        repertoire_exchange_service = RepertoireExchangeService(
            conn,
            party_service=party_service,
            work_service=work_service,
            contract_service=contract_service,
            rights_service=rights_service,
            asset_service=asset_service,
            data_root=self.data_root,
        )
        party_exchange_service = PartyExchangeService(
            conn,
            party_service=party_service,
            settings_mutations=settings_mutations,
            profile_name=Path(self.db_path).name,
        )
        if AUTHENTICITY_FEATURE_AVAILABLE:
            authenticity_key_service = AuthenticityKeyService(
                conn,
                profile_kv=profile_kv,
                settings_root=Path(self.settings_path).resolve().parent,
            )
            authenticity_manifest_service = AuthenticityManifestService(
                conn,
                track_service=track_service,
                release_service=release_service,
                work_service=work_service,
                rights_service=rights_service,
                asset_service=asset_service,
                key_service=authenticity_key_service,
            )
            audio_watermark_service = AudioWatermarkService()
            audio_authenticity_service = AudioAuthenticityService(
                conn,
                key_service=authenticity_key_service,
                manifest_service=authenticity_manifest_service,
                watermark_service=audio_watermark_service,
                tag_service=audio_tag_service,
                app_version=_app_version_text(),
            )
            forensic_watermark_service = ForensicWatermarkService()
            forensic_export_service = ForensicExportCoordinator(
                conn=conn,
                track_service=track_service,
                release_service=release_service,
                tag_service=audio_tag_service,
                key_service=authenticity_key_service,
                conversion_service=AudioConversionService(),
                watermark_service=forensic_watermark_service,
            )
        else:
            authenticity_key_service = None
            authenticity_manifest_service = None
            audio_watermark_service = None
            audio_authenticity_service = None
            forensic_watermark_service = None
            forensic_export_service = None

        return BackgroundAppServiceBundle(
            conn=conn,
            settings=settings,
            track_service=track_service,
            release_service=release_service,
            license_service=license_service,
            catalog_reads=catalog_reads,
            custom_field_definitions=custom_field_definitions,
            custom_field_values=custom_field_values,
            xml_export_service=xml_export_service,
            xml_import_service=xml_import_service,
            exchange_service=exchange_service,
            repertoire_exchange_service=repertoire_exchange_service,
            party_exchange_service=party_exchange_service,
            master_transfer_service=MasterTransferService(
                exchange_service=exchange_service,
                repertoire_exchange_service=repertoire_exchange_service,
                license_service=license_service,
                contract_template_service=contract_template_service,
                app_version=_app_version_text(),
            ),
            quality_service=QualityDashboardService(
                conn,
                track_service=track_service,
                release_service=release_service,
                data_root=self.data_root,
            ),
            party_service=party_service,
            work_service=work_service,
            contract_service=contract_service,
            license_migration_service=license_migration_service,
            rights_service=rights_service,
            asset_service=asset_service,
            workflow_service=workflow_service,
            global_search_service=global_search_service,
            relationship_explorer_service=relationship_explorer_service,
            gs1_settings_service=gs1_settings_service,
            gs1_integration_service=GS1IntegrationService(
                GS1MetadataRepository(conn),
                gs1_settings_service,
                track_service,
            ),
            audio_tag_service=audio_tag_service,
            tagged_audio_export_service=TaggedAudioExportService(audio_tag_service),
            track_import_repair_queue=track_import_repair_queue,
            history_manager=HistoryManager(
                conn,
                settings,
                self.db_path,
                self.history_dir,
                self.data_root,
                self.backups_dir,
            ),
            database_maintenance=DatabaseMaintenanceService(self.backups_dir),
            settings_reads=settings_reads,
            settings_mutations=settings_mutations,
            profile_kv=profile_kv,
            authenticity_key_service=authenticity_key_service,
            authenticity_manifest_service=authenticity_manifest_service,
            audio_watermark_service=audio_watermark_service,
            audio_authenticity_service=audio_authenticity_service,
            forensic_watermark_service=forensic_watermark_service,
            forensic_export_service=forensic_export_service,
        )
