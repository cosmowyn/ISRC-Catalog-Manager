from tests.exchange._support import ExchangeServiceTestCase


class ExchangeJsonTests(ExchangeServiceTestCase):
    test_json_round_trip_preserves_release_and_custom_fields = (
        ExchangeServiceTestCase.case_json_round_trip_preserves_release_and_custom_fields
    )
    test_json_export_prefers_authoritative_governed_work_metadata = (
        ExchangeServiceTestCase.case_json_export_prefers_authoritative_governed_work_metadata
    )
    test_import_json_normalizes_allowed_title_fields_and_preserves_existing_case_and_codes = (
        ExchangeServiceTestCase.case_import_json_normalizes_allowed_title_fields_and_preserves_existing_case_and_codes
    )
    test_import_json_respects_mapping_when_skipping_custom_field = (
        ExchangeServiceTestCase.case_import_json_respects_mapping_when_skipping_custom_field
    )
    test_import_json_persists_failed_rows_to_repair_queue_without_creating_live_orphans = (
        ExchangeServiceTestCase.case_import_json_persists_failed_rows_to_repair_queue_without_creating_live_orphans
    )
    test_repair_queue_row_can_be_reapplied_through_governed_import_seam = (
        ExchangeServiceTestCase.case_repair_queue_row_can_be_reapplied_through_governed_import_seam
    )
    test_export_json_reports_staged_progress = (
        ExchangeServiceTestCase.case_export_json_reports_staged_progress
    )
    test_import_json_reports_staged_progress_to_completion = (
        ExchangeServiceTestCase.case_import_json_reports_staged_progress_to_completion
    )


del ExchangeServiceTestCase
