from tests.exchange._support import ExchangeServiceTestCase


class ExchangeCsvImportTests(ExchangeServiceTestCase):
    test_update_mode_skips_unmatched_rows = (
        ExchangeServiceTestCase.case_update_mode_skips_unmatched_rows
    )
    test_import_csv_creates_track_from_multiple_columns = (
        ExchangeServiceTestCase.case_import_csv_creates_track_from_multiple_columns
    )
    test_import_csv_detects_semicolon_delimiter = (
        ExchangeServiceTestCase.case_import_csv_detects_semicolon_delimiter
    )
    test_import_csv_detects_pipe_delimiter = (
        ExchangeServiceTestCase.case_import_csv_detects_pipe_delimiter
    )
    test_custom_csv_delimiter_refresh_and_import_preserve_quoted_values = (
        ExchangeServiceTestCase.case_custom_csv_delimiter_refresh_and_import_preserve_quoted_values
    )
    test_import_csv_rejects_invalid_explicit_delimiter = (
        ExchangeServiceTestCase.case_import_csv_rejects_invalid_explicit_delimiter
    )
    test_import_csv_normalizes_hms_track_length_target = (
        ExchangeServiceTestCase.case_import_csv_normalizes_hms_track_length_target
    )
    test_import_csv_invalid_track_length_text_still_fails_row = (
        ExchangeServiceTestCase.case_import_csv_invalid_track_length_text_still_fails_row
    )
    test_update_mode_prefers_authoritative_governed_work_metadata = (
        ExchangeServiceTestCase.case_update_mode_prefers_authoritative_governed_work_metadata
    )
    test_merge_mode_prefers_authoritative_governed_work_metadata = (
        ExchangeServiceTestCase.case_merge_mode_prefers_authoritative_governed_work_metadata
    )


del ExchangeServiceTestCase
