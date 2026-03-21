from tests.exchange._support import ExchangeServiceTestCase


class ExchangeCustomFieldTests(ExchangeServiceTestCase):
    test_supported_import_targets_include_active_non_blob_custom_fields = (
        ExchangeServiceTestCase.case_supported_import_targets_include_active_non_blob_custom_fields
    )
    test_import_csv_maps_arbitrary_source_column_to_active_custom_field = (
        ExchangeServiceTestCase.case_import_csv_maps_arbitrary_source_column_to_active_custom_field
    )


del ExchangeServiceTestCase
