from tests.exchange._support import ExchangeServiceTestCase


class ExchangeJsonTests(ExchangeServiceTestCase):
    test_json_round_trip_preserves_release_and_custom_fields = (
        ExchangeServiceTestCase.case_json_round_trip_preserves_release_and_custom_fields
    )
    test_import_json_normalizes_allowed_title_fields_and_preserves_existing_case_and_codes = (
        ExchangeServiceTestCase.case_import_json_normalizes_allowed_title_fields_and_preserves_existing_case_and_codes
    )
    test_import_json_respects_mapping_when_skipping_custom_field = (
        ExchangeServiceTestCase.case_import_json_respects_mapping_when_skipping_custom_field
    )


del ExchangeServiceTestCase
