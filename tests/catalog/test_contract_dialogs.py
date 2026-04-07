from tests.catalog._contract_rights_asset_support import ContractRightsAssetServiceTestCase


class ContractDialogTests(ContractRightsAssetServiceTestCase):
    test_contract_browser_uses_compact_action_cluster = (
        ContractRightsAssetServiceTestCase.case_contract_browser_uses_compact_action_cluster
    )
    test_contract_document_editor_open_and_export_helpers = (
        ContractRightsAssetServiceTestCase.case_contract_document_editor_open_and_export_helpers
    )
    test_contract_document_editor_export_button_ignores_clicked_bool_payload = (
        ContractRightsAssetServiceTestCase.case_contract_document_editor_export_button_ignores_clicked_bool_payload
    )
    test_contract_editor_selector_widgets_round_trip_known_reference_ids = (
        ContractRightsAssetServiceTestCase.case_contract_editor_selector_widgets_round_trip_known_reference_ids
    )
    test_contract_editor_preserves_unresolved_reference_ids_in_dialog_payload = (
        ContractRightsAssetServiceTestCase.case_contract_editor_preserves_unresolved_reference_ids_in_dialog_payload
    )
    test_contract_editor_structured_obligations_round_trip_all_fields = (
        ContractRightsAssetServiceTestCase.case_contract_editor_structured_obligations_round_trip_all_fields
    )
    test_contract_editor_structured_parties_round_trip_known_and_typed_entries = (
        ContractRightsAssetServiceTestCase.case_contract_editor_structured_parties_round_trip_known_and_typed_entries
    )
    test_contract_editor_generates_registry_values_and_keeps_sha256_distinct = (
        ContractRightsAssetServiceTestCase.case_contract_editor_generates_registry_values_and_keeps_sha256_distinct
    )
    test_contract_editor_party_editor_guides_near_duplicates_without_extra_clutter = (
        ContractRightsAssetServiceTestCase.case_contract_editor_party_editor_guides_near_duplicates_without_extra_clutter
    )
    test_contract_editor_party_editor_supports_quick_create_and_edit = (
        ContractRightsAssetServiceTestCase.case_contract_editor_party_editor_supports_quick_create_and_edit
    )


del ContractRightsAssetServiceTestCase
