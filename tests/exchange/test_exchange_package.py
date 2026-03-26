from tests.exchange._support import ExchangeServiceTestCase


class ExchangePackageTests(ExchangeServiceTestCase):
    test_package_export_writes_manifest_and_media = (
        ExchangeServiceTestCase.case_package_export_writes_manifest_and_media
    )
    test_package_export_prefers_authoritative_governed_work_metadata = (
        ExchangeServiceTestCase.case_package_export_prefers_authoritative_governed_work_metadata
    )
    test_package_export_omits_legacy_license_files_column = (
        ExchangeServiceTestCase.case_package_export_omits_legacy_license_files_column
    )
    test_package_export_includes_shared_album_art_once = (
        ExchangeServiceTestCase.case_package_export_includes_shared_album_art_once
    )
    test_inspect_package_reads_manifest_preview = (
        ExchangeServiceTestCase.case_inspect_package_reads_manifest_preview
    )
    test_package_import_round_trip_restores_media_and_release_artwork = (
        ExchangeServiceTestCase.case_package_import_round_trip_restores_media_and_release_artwork
    )
    test_package_import_round_trip_restores_shared_album_art_without_child_rewrite = (
        ExchangeServiceTestCase.case_package_import_round_trip_restores_shared_album_art_without_child_rewrite
    )
    test_package_import_reuses_duplicate_track_rows_and_preserves_source_release_ids = (
        ExchangeServiceTestCase.case_package_import_reuses_duplicate_track_rows_and_preserves_source_release_ids
    )
    test_package_round_trip_preserves_database_backed_media_modes = (
        ExchangeServiceTestCase.case_package_round_trip_preserves_database_backed_media_modes
    )
    test_package_import_supports_legacy_relative_media_without_index = (
        ExchangeServiceTestCase.case_package_import_supports_legacy_relative_media_without_index
    )
    test_import_package_respects_mapping_when_skipping_custom_field = (
        ExchangeServiceTestCase.case_import_package_respects_mapping_when_skipping_custom_field
    )


del ExchangeServiceTestCase
