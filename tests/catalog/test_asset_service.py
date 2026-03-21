from tests.catalog._contract_rights_asset_support import ContractRightsAssetServiceTestCase


class AssetServiceTests(ContractRightsAssetServiceTestCase):
    test_asset_validation_catches_missing_approved_master = (
        ContractRightsAssetServiceTestCase.case_asset_validation_catches_missing_approved_master
    )
    test_asset_can_round_trip_between_database_and_managed_file_modes = (
        ContractRightsAssetServiceTestCase.case_asset_can_round_trip_between_database_and_managed_file_modes
    )
    test_asset_update_listing_validation_and_delete_cleanup = (
        ContractRightsAssetServiceTestCase.case_asset_update_listing_validation_and_delete_cleanup
    )


del ContractRightsAssetServiceTestCase
