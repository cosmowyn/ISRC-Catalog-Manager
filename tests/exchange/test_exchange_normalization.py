from tests.exchange._support import ExchangeServiceTestCase


class ExchangeNormalizationTests(ExchangeServiceTestCase):
    test_import_csv_normalizes_allowed_title_fields_after_mapping_and_preserves_codes = (
        ExchangeServiceTestCase.case_import_csv_normalizes_allowed_title_fields_after_mapping_and_preserves_codes
    )
    test_normalize_text_target_restores_only_exact_compound_spans = (
        ExchangeServiceTestCase.case_normalize_text_target_restores_only_exact_compound_spans
    )


del ExchangeServiceTestCase
