from tests.exchange._support import ExchangeServiceTestCase


class ExchangeXlsxImportTests(ExchangeServiceTestCase):
    test_import_xlsx_normalizes_track_length_target_values = (
        ExchangeServiceTestCase.case_import_xlsx_normalizes_track_length_target_values
    )
    test_import_xlsx_normalizes_allowed_title_fields_and_preserves_codes = (
        ExchangeServiceTestCase.case_import_xlsx_normalizes_allowed_title_fields_and_preserves_codes
    )


del ExchangeServiceTestCase
