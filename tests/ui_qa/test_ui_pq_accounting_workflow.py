import pytest

from isrc_manager.qa.assertions import require_inventory_area

pytestmark = pytest.mark.ui_pq


def test_ui_pq_accounting_workflow(ui_pq_harness):
    require_inventory_area(ui_pq_harness.inventory, "accounting_royalties")
    event = next(
        event for event in ui_pq_harness.evidence.events if event.test_id == "UI-PQ-ACC-001"
    )
    assert event.status == "passed"
    assert event.data["workflow_status"] == "fully_ui_led"
    assert event.data["service_layer_shortcuts"] == []
    assert event.data["counts"]["Invoices"] >= 2
    assert event.data["counts"]["AccountingTransactions"] >= 7
    assert event.data["counts"]["FinancialCommandLog"] >= 7
    assert event.data["party_ledger_balance_minor"] == 0
    assert event.data["payment_total_minor"] == 12_100
    assert event.data["credit_total_minor"] == 12_100
    assert event.data["payout_total_minor"] == 15_000
    assert len(event.data["visual_evidence"]) >= 8
    assert not any(
        deviation.test_id == "UI-PQ-ACC-001" for deviation in ui_pq_harness.deviations.deviations
    )
