# Invoice Workspace and Ledger-Backed Billing Engine

This implementation adds the accounting foundation for invoice, payment, credit-note, royalty, template, and report workflows.

## Current accounting scope

- Money is stored in integer minor units.
- Ledger transactions and entries are append-only after posting.
- Invoice issue, payment, credit note, royalty payable approval, and artist payout commands are idempotency-keyed.
- Invoice numbers, credit-note numbers, and royalty statement numbers are generated through the code registry.
- Party balances and invoice settlement state are derived from ledger entries, not mutable status totals.

## Schema versions

- Schema version 44 introduced the base invoicing/accounting tables.
- Schema version 45 adds line-level credit-note allocations and immutable invoice output artifact records.

## Credit-note allocations

Credit notes can be issued as aggregate corrections or allocated to immutable invoice line snapshots.
Line allocations are persisted in `CreditNoteLineAllocations` and validated so a line cannot be credited beyond its original net/VAT amounts less prior issued credit allocations.

## Export artifacts

HTML invoice export renders through the same service path as preview, creates an immutable resolved snapshot, and can register an immutable `InvoiceOutputArtifacts` row for the exported HTML artifact.
PDF rendering is intentionally not faked; it should be added through an explicit renderer adapter that writes a real PDF artifact linked to the resolved snapshot.

## Remaining implementation notes

- PDF generation still needs a renderer adapter decision.
- Royalty statement rendering should get a statement-specific symbol catalog before broad UI exposure.
- The repository-wide Black gate currently fails on pre-existing formatting drift outside this feature slice.
