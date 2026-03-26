from tests.exchange._repertoire_exchange_support import SearchAndRepertoireExchangeTestCase


class RepertoireExchangeServiceTests(SearchAndRepertoireExchangeTestCase):
    test_repertoire_exchange_json_round_trip = (
        SearchAndRepertoireExchangeTestCase.case_repertoire_exchange_json_round_trip
    )
    test_repertoire_exchange_json_round_trip_preserves_expanded_party_metadata = (
        SearchAndRepertoireExchangeTestCase.case_repertoire_exchange_json_round_trip_preserves_expanded_party_metadata
    )
    test_repertoire_exchange_package_round_trip_preserves_files_and_document_chain = (
        SearchAndRepertoireExchangeTestCase.case_repertoire_exchange_package_round_trip_preserves_files_and_document_chain
    )
    test_repertoire_exchange_package_round_trip_preserves_database_backed_files = (
        SearchAndRepertoireExchangeTestCase.case_repertoire_exchange_package_round_trip_preserves_database_backed_files
    )
    test_repertoire_exchange_xlsx_csv_and_schema_validation = (
        SearchAndRepertoireExchangeTestCase.case_repertoire_exchange_xlsx_csv_and_schema_validation
    )
    test_repertoire_import_reports_staged_progress_to_completion = (
        SearchAndRepertoireExchangeTestCase.case_repertoire_import_reports_staged_progress_to_completion
    )


del SearchAndRepertoireExchangeTestCase
