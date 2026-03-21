from tests.catalog._contract_rights_asset_support import ContractRightsAssetServiceTestCase


class ContractServiceTests(ContractRightsAssetServiceTestCase):
    test_contract_deadlines_and_document_validation = (
        ContractRightsAssetServiceTestCase.case_contract_deadlines_and_document_validation
    )
    test_contract_update_search_export_and_delete_cleanup = (
        ContractRightsAssetServiceTestCase.case_contract_update_search_export_and_delete_cleanup
    )
    test_contract_documents_support_managed_and_database_storage_modes = (
        ContractRightsAssetServiceTestCase.case_contract_documents_support_managed_and_database_storage_modes
    )
    test_contract_document_update_preserves_storage_metadata_on_noop_save = (
        ContractRightsAssetServiceTestCase.case_contract_document_update_preserves_storage_metadata_on_noop_save
    )
    test_contract_document_storage_mode_round_trip_via_update = (
        ContractRightsAssetServiceTestCase.case_contract_document_storage_mode_round_trip_via_update
    )
    test_contract_validation_rejects_invalid_date_ranges = (
        ContractRightsAssetServiceTestCase.case_contract_validation_rejects_invalid_date_ranges
    )


del ContractRightsAssetServiceTestCase
