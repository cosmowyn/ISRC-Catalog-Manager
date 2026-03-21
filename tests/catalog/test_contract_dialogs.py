from tests.catalog._contract_rights_asset_support import ContractRightsAssetServiceTestCase


class ContractDialogTests(ContractRightsAssetServiceTestCase):
    test_contract_document_editor_open_and_export_helpers = (
        ContractRightsAssetServiceTestCase.case_contract_document_editor_open_and_export_helpers
    )
    test_contract_editor_selector_widgets_round_trip_known_reference_ids = (
        ContractRightsAssetServiceTestCase.case_contract_editor_selector_widgets_round_trip_known_reference_ids
    )
    test_contract_editor_preserves_unresolved_reference_ids_in_dialog_payload = (
        ContractRightsAssetServiceTestCase.case_contract_editor_preserves_unresolved_reference_ids_in_dialog_payload
    )


del ContractRightsAssetServiceTestCase
