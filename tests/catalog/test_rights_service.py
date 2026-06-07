from tests.catalog._contract_rights_asset_support import ContractRightsAssetServiceTestCase


class RightsServiceTests(ContractRightsAssetServiceTestCase):
    test_rights_conflict_detection_and_missing_source_contract = (
        ContractRightsAssetServiceTestCase.case_rights_conflict_detection_and_missing_source_contract
    )
    test_rights_filters_summary_update_and_delete = (
        ContractRightsAssetServiceTestCase.case_rights_filters_summary_update_and_delete
    )
    test_explicit_ownership_ledgers_override_inferred_control = (
        ContractRightsAssetServiceTestCase.case_explicit_ownership_ledgers_override_inferred_control
    )
    test_rights_validation_normalization_and_conflict_skip_branches = (
        ContractRightsAssetServiceTestCase.case_rights_validation_normalization_and_conflict_skip_branches
    )


del ContractRightsAssetServiceTestCase
