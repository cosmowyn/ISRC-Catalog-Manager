from tests.exchange._support import ExchangeServiceTestCase


class ExchangeCsvInspectionTests(ExchangeServiceTestCase):
    test_inspect_csv_suggests_known_headers = (
        ExchangeServiceTestCase.case_inspect_csv_suggests_known_headers
    )
    test_inspect_csv_preserves_quoted_commas = (
        ExchangeServiceTestCase.case_inspect_csv_preserves_quoted_commas
    )
    test_inspect_csv_detects_semicolon_delimiter = (
        ExchangeServiceTestCase.case_inspect_csv_detects_semicolon_delimiter
    )
    test_inspect_csv_detects_tab_delimiter = (
        ExchangeServiceTestCase.case_inspect_csv_detects_tab_delimiter
    )


del ExchangeServiceTestCase
