from tests.catalog._contract_rights_asset_support import ContractRightsAssetServiceTestCase


class RightsDialogTests(ContractRightsAssetServiceTestCase):
    test_right_editor_supports_party_quick_create_and_edit = (
        ContractRightsAssetServiceTestCase.case_right_editor_supports_party_quick_create_and_edit
    )


del ContractRightsAssetServiceTestCase
