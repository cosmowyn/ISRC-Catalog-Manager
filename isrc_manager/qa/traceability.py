"""Traceability matrix generation for UI PQ coverage."""

from __future__ import annotations

import csv
from dataclasses import asdict, dataclass
from pathlib import Path

from .deviations import DeviationRecorder
from .inventory import UIInventoryItem


@dataclass(slots=True)
class TraceabilityEntry:
    test_id: str
    ui_area: str
    workflow: str
    ui_object: str
    qualification_level: str
    automation_status: str
    preconditions: str
    test_data: str
    steps: str
    expected_result: str
    data_objects: str
    dependencies: str
    evidence: str
    deviation_criteria: str
    manual_followup_status: str = ""
    rationale: str = ""


@dataclass(slots=True)
class TraceabilityRow:
    inventory_id: str
    ui_area: str
    kind: str
    ui_object: str
    object_name: str
    test_id: str
    qualification_level: str
    coverage_status: str
    automation_status: str
    manual_followup_status: str
    rationale: str
    evidence: str


TRACEABILITY_COLUMNS = tuple(TraceabilityRow.__dataclass_fields__.keys())


def default_traceability_entries() -> list[TraceabilityEntry]:
    """Broad first-pass qualification matrix.

    The rows are intentionally honest: areas not yet fully automated are marked pending/manual
    and will remain visible in the generated traceability matrix.
    """

    return [
        TraceabilityEntry(
            "UI-PQ-SMOKE-001",
            "startup_profile",
            "Launch application, isolate QA profile, and verify main shell readiness.",
            "mainWindow/profile/menu shell",
            "UI Reachability Qualification",
            "automated",
            "QT_QPA_PLATFORM=offscreen; QA temp directories active.",
            "Temporary profile/database created by QA harness.",
            "Launch App, show main window, verify database path, menu bar, profile controls.",
            "Main shell opens without unhandled exceptions and uses temp QA storage.",
            "SQLite QA profile",
            "PySide6, local filesystem",
            "evidence.json, ui_inventory.json",
            "Unhandled startup exception, missing profile control, or real user data path.",
        ),
        TraceabilityEntry(
            "UI-PQ-MENU-001",
            "unknown",
            "Inventory all menus/actions and identify unclassified UI.",
            "QAction/QMenu",
            "UI Inventory Qualification",
            "automated",
            "Main window launched.",
            "Runtime QAction and widget tree.",
            "Discover actions, menus, docks, tabs, fields, buttons, and views.",
            "All discovered surfaces are written to inventory and traceability artifacts.",
            "UI inventory",
            "PySide6 object tree",
            "ui_inventory.json, traceability_matrix.csv",
            "Discovered item cannot be classified or mapped to a qualification area.",
            manual_followup_status="classification follow-up required for unknown items",
            rationale="Unknown items are deviations until assigned to a UI area.",
        ),
        TraceabilityEntry(
            "UI-PQ-CAT-001",
            "catalog",
            "Catalog table, track creation, track editing entry points, album operations.",
            "catalog table/actions",
            "Functional Workflow Qualification",
            "automated",
            "QA profile open.",
            "UI-populated Add Track and Edit Track forms.",
            "Create a track through Add Track UI, edit it through Edit Track UI, refresh catalog UI, assert row and database state.",
            "Track exists in database, edited values persist, screenshot baseline comparison passes, and row is visible to the catalog workflow.",
            "Tracks, Albums, TrackArtists",
            "Add Track panel, EditDialog, catalog table controller",
            "evidence.json, business_workflow_manifest.json",
            "Track cannot be created, edited, refreshed, visually captured, or verified in the database.",
        ),
        TraceabilityEntry(
            "UI-PQ-REL-001",
            "works_releases_parties",
            "Track to work, release, and party relationship qualification.",
            "work/release/party managers",
            "Relationship Qualification",
            "automated",
            "QA track exists.",
            "UI-populated Party Manager, Work Manager, and Release Browser surfaces.",
            "Create Party and Work records through manager dialogs; verify Add Track-created release in Release Browser and database links.",
            "Related records exist, link to the QA track/work, appear in their manager tables, and pass screenshot baseline comparison.",
            "Parties, Works, Releases, ReleaseTracks",
            "PartyManagerPanel, WorkBrowserPanel, ReleaseBrowserPanel",
            "evidence.json, business_workflow_manifest.json",
            "Missing relationship, broken manager reachability, screenshot drift, or database mismatch.",
        ),
        TraceabilityEntry(
            "UI-PQ-CON-001",
            "contracts_rights",
            "Contract/license and rights relationship qualification.",
            "contract manager/rights matrix",
            "Relationship Qualification",
            "automated",
            "QA party/work/track/release exist.",
            "UI-populated Contract Manager and Rights Matrix dialogs.",
            "Create contract linked to party/work/track/release through Contract Manager; create right through Rights Matrix; verify links.",
            "Contract detail and rights records reference the expected entities, appear in manager tables, and pass screenshot baseline comparison.",
            "Contracts, ContractParties, ContractWorkLinks, RightsRecords",
            "ContractBrowserPanel, ContractEditorDialog, RightsBrowserPanel, RightEditorDialog",
            "evidence.json, business_workflow_manifest.json",
            "Contract/right links missing, manager surface not traceable, screenshot drift, or database mismatch.",
        ),
        TraceabilityEntry(
            "UI-PQ-ACC-001",
            "accounting_royalties",
            "Invoices, royalties, ledgers, statements, payouts, reports.",
            "Royalties & Accounting workspace",
            "Functional Workflow Qualification",
            "automated",
            "QA party, track, work, release, contract, and right exist.",
            "UI-entered invoice, payment, credit, royalty, statement, payout, and report data.",
            "Open the Royalties & Accounting workspace; populate invoice controls; create draft invoices; issue invoices; enter payments; create a credit note; create and post a royalty calculation; generate a statement; record payouts; refresh reports; capture each UI state; verify database and ledger state.",
            "Invoices, credit notes, royalty statements, payouts, command logs, accounting entries, reports, and screenshots persist with balanced ledgers.",
            "Invoices, InvoicePayments, CreditNotes, RoyaltyCalculations, RoyaltyStatements, ArtistPayouts, AccountingTransactions",
            "InvoiceWorkspacePanel UI controls, SQLite ledger verification, VisualQualificationService",
            "evidence.json, business_workflow_manifest.json",
            "Accounting chain fails, ledger imbalance is detected, or settlement reports disagree with persisted data.",
        ),
        TraceabilityEntry(
            "UI-PQ-SC-001",
            "soundcloud",
            "SoundCloud publishing and account/token surfaces in mocked/no-network mode.",
            "SoundCloud UI/actions",
            "Functional Workflow Qualification",
            "automated",
            "No-network guard active; QA track exists.",
            "Mock public account profile, local watermarked WAV upload path, local artwork, and dialog metadata fields.",
            "Open the SoundCloud publish dialog; configure private plan options, metadata, artwork, album/track selection, and watermarked source; click Refresh preflight; click Publish; execute the no-network runner through the dialog; validate progress and completion UI; assert no secret-bearing columns are present.",
            "No real network or credential write occurs; public profile, plan, watermarked source, artwork, publication, run state, progress UI, completion UI, and screenshots are traceable.",
            "SoundCloudAccounts, SoundCloudPublishRuns, SoundCloudPublishRunItems, SoundCloudTrackPublications",
            "SoundCloudPublishDialog, SoundCloudPublishPlanner, mocked no-network publish runner, SoundCloudSQLiteRepository",
            "evidence.json, business_workflow_manifest.json",
            "Live network attempted, credentials written to SQLite, or mocked publish state missing.",
        ),
        TraceabilityEntry(
            "UI-PQ-AUTH-001",
            "authenticity",
            "Authenticity, watermark, forensic, and verification workflows.",
            "authenticity/watermark dialogs",
            "Functional Workflow Qualification",
            "automated",
            "QA profile open; no live external calls.",
            "Synthetic WAV master, local signing key, signed sidecar, and forensic export metadata.",
            "Attach deterministic audio, generate/resolve an authenticity key, preview direct-watermark export, export a signed watermarked master, verify the exported audio and sidecar, open verification UI, collect forensic export metadata, export a forensic WAV copy, inspect it, and open the forensic inspection UI.",
            "Direct authenticity report is verified with a valid signature; forensic inspection resolves the created export record; dialogs and service outputs are captured as evidence.",
            "AuthenticityKeys, AuthenticityManifests, ForensicWatermarkExports, DerivativeExportBatches, TrackAudioDerivatives",
            "AudioAuthenticityService, ForensicExportCoordinator, Authenticity dialogs, Forensic dialogs, VisualQualificationService",
            "evidence.json, business_workflow_manifest.json",
            "Key generation fails, direct watermark export fails, signature verification fails, forensic export/inspection fails, or result dialogs are not captured.",
        ),
        TraceabilityEntry(
            "UI-PQ-IMP-001",
            "import_export",
            "Import/export, generated metadata, packages, ledgers, manifests.",
            "import/export actions/dialogs",
            "Output Qualification",
            "automated",
            "QA profile open.",
            "Temporary generated report, HTML document, CSV, and PDF artifacts.",
            "Generate deterministic report/document artifacts, compare them with baselines, and structurally inspect the generated PDF.",
            "Report, document, CSV, and PDF artifacts are present, parseable, and baseline-comparable.",
            "HTML, CSV, PDF, JSON reports",
            "VisualQualificationService, QPdfWriter, QTextDocument",
            "evidence.json, visual/generated_output_manifest.json",
            "Generated artifact missing, PDF structurally invalid, or comparison differs from baseline.",
        ),
        TraceabilityEntry(
            "UI-PQ-DIAG-001",
            "diagnostics",
            "Diagnostics dashboard, repair, and recovery reporting.",
            "diagnostics/repair actions",
            "Error/Recovery Qualification",
            "automated",
            "QA profile open.",
            "Local deterministic database.",
            "Build diagnostics report, verify SQLite integrity, create backup, restore backup to isolated target, and verify restored integrity.",
            "Diagnostics report returns healthy core checks; backup and isolated restore both pass integrity validation.",
            "Diagnostics reports, SQLite profile, backup artifact, isolated restore artifact",
            "DiagnosticsController, diagnostics report builder, DatabaseMaintenanceService",
            "evidence.json",
            "Diagnostics report fails, integrity fails, backup cannot be created, or isolated restore is invalid.",
        ),
        TraceabilityEntry(
            "UI-PQ-SET-001",
            "settings_theme_help",
            "Settings, theme/QSS, help, documentation, about surfaces.",
            "settings/theme/help actions",
            "UI Reachability Qualification",
            "automated",
            "QA profile open.",
            "Runtime UI inventory.",
            "Capture main window screenshot, open/capture/close help and about dialogs, compare visual baselines, and validate prepared theme payload.",
            "Screenshots are nonblank, visual baselines match, dialogs are reachable, and theme stylesheet generation succeeds.",
            "QSettings, theme values, help topics",
            "Settings dialogs, help content, VisualQualificationService, theme controller",
            "evidence.json, visual/visual_manifest.json",
            "Dialog not reachable, screenshot blank, baseline mismatch, or theme payload invalid.",
        ),
        TraceabilityEntry(
            "UI-PQ-HELP-001",
            "help_documentation",
            "Validate Help manual coverage against runtime inventory, workflow playbooks, per-chapter screenshot references, and chapter depth.",
            "Help manual",
            "Documentation Qualification",
            "automated",
            "UI inventory and visual screenshot baseline are available.",
            "Runtime UI inventory, HelpChapter corpus, docs/help/screenshots.",
            "Refresh checked-in Help screenshots, generate one screenshot reference per chapter, copy screenshot assets, compare inventory labels and workflow requirements against the help corpus, and write help_coverage.json.",
            "Help documentation reports 100% coverage with zero findings.",
            "HelpChapter content, UI inventory, screenshot files",
            "help_content.py, HelpContentsDialog, HelpCoverageReport",
            "evidence.json, help/help_coverage.json, help/validated_help_manual.html",
            "Missing workflow coverage, missing per-chapter screenshot, shallow chapter, or user-facing label absent from Help.",
        ),
        TraceabilityEntry(
            "UI-PQ-MEDIA-001",
            "media_audio",
            "Media player, audio attachment, conversion, derivative/export ledger.",
            "media player/audio actions",
            "Performance/Responsiveness Qualification",
            "automated",
            "QA profile open.",
            "Synthetic local WAV fixture and deterministic no-ffmpeg conversion boundary.",
            "Attach audio through TrackService, render the bulk attach review dialog, route the Media Player command to the selected track, export a managed lossy derivative through the coordinator using a controlled conversion service, open the derivative ledger, and verify persisted batch/item rows.",
            "Attached audio is fetchable, media player command targets the QA track, derivative export writes one completed batch/item, and the ledger drill-in surface is captured.",
            "Tracks media columns, TrackAudioWaveformCache, DerivativeExportBatches, TrackAudioDerivatives",
            "TrackService, media player controller, BulkAudioAttachDialog, ManagedDerivativeExportCoordinator, DerivativeLedgerService, VisualQualificationService",
            "evidence.json, business_workflow_manifest.json",
            "Audio attachment fails, media player target is wrong, derivative conversion/export fails, ledger rows are absent, or ledger UI is not captured.",
        ),
        TraceabilityEntry(
            "UI-PQ-ASSET-001",
            "assets_deliverables",
            "Deliverables, asset versions, and derivative ledger workspace.",
            "Deliverables and Asset Versions",
            "Functional Workflow Qualification",
            "automated",
            "QA profile open with a catalog track.",
            "Synthetic asset registry row created through AssetService.",
            "Seed a primary master asset, open the Deliverables and Asset Versions dock from the runtime action, verify asset selection/search, switch to the derivative ledger tab, and confirm dock controls are present in inventory.",
            "Asset registry action opens the dock, the seeded asset is visible and selectable, the derivative ledger tab is reachable, and discovered assets-deliverables controls are covered.",
            "AssetVersions, derivative ledger UI state",
            "AssetService, AssetBrowserPanel, catalog workspace dock",
            "evidence.json, business_workflow_manifest.json",
            "Asset registry action fails, seeded asset is not visible, derivative ledger is unreachable, or dock controls are missing from inventory.",
        ),
        TraceabilityEntry(
            "UI-PQ-MISC-001",
            "assets_deliverables",
            "Assets, deliverables, code registry, GS1, search, logs, reports, updates.",
            "secondary manager surfaces",
            "UI Inventory Qualification",
            "pending",
            "QA profile open.",
            "Runtime inventory.",
            "Map discovered secondary surfaces to pending/manual qualification entries.",
            "Secondary surfaces appear in traceability matrix and deviations where incomplete.",
            "Various secondary records",
            "Feature-specific services",
            "traceability_matrix.csv, deviations.csv",
            "Surface omitted from traceability.",
            manual_followup_status="feature-specific workflow automation pending",
        ),
    ]


def _matching_entry(
    item: UIInventoryItem, entries: list[TraceabilityEntry]
) -> TraceabilityEntry | None:
    exact = [entry for entry in entries if entry.ui_area == item.ui_area]
    if exact:
        return exact[0]
    secondary_areas = {
        "assets_deliverables",
        "code_registry",
        "gs1",
        "history_recovery",
        "logs_support",
        "recovery",
        "reports",
        "search",
        "update_release",
    }
    if item.ui_area in secondary_areas:
        return next((entry for entry in entries if entry.test_id == "UI-PQ-MISC-001"), None)
    return None


def build_traceability_matrix(
    inventory: list[UIInventoryItem],
    *,
    deviations: DeviationRecorder,
    entries: list[TraceabilityEntry] | None = None,
    database_path: str = "",
    evidence_path: str = "",
) -> list[TraceabilityRow]:
    matrix_entries = entries or default_traceability_entries()
    rows: list[TraceabilityRow] = []
    for item in inventory:
        entry = _matching_entry(item, matrix_entries)
        if entry is None:
            rows.append(
                TraceabilityRow(
                    inventory_id=item.inventory_id,
                    ui_area=item.ui_area,
                    kind=item.kind,
                    ui_object=item.text or item.object_name or item.inventory_id,
                    object_name=item.object_name,
                    test_id="",
                    qualification_level="",
                    coverage_status="uncovered",
                    automation_status="missing",
                    manual_followup_status="required",
                    rationale="No matrix row currently maps this discovered UI surface.",
                    evidence="deviations.csv",
                )
            )
            deviations.add(
                test_id="UI-PQ-TRACE-001",
                severity="high",
                ui_area=item.ui_area,
                workflow="Traceability enforcement",
                ui_object=item.inventory_id,
                step="Compare inventory item against matrix",
                expected="Every discovered UI surface maps to automated, pending, or out-of-scope coverage.",
                actual="No traceability row mapped this UI surface.",
                database_path=database_path,
                evidence_path=evidence_path,
                coverage_status="uncovered",
                recommended_followup="Classify the UI surface and add automated or pending qualification coverage.",
            )
            continue

        coverage_status = (
            "covered"
            if entry.automation_status == "automated"
            else (
                "pending_manual"
                if "pending" in entry.automation_status or entry.manual_followup_status
                else entry.automation_status
            )
        )
        rows.append(
            TraceabilityRow(
                inventory_id=item.inventory_id,
                ui_area=item.ui_area,
                kind=item.kind,
                ui_object=item.text or item.object_name or item.inventory_id,
                object_name=item.object_name,
                test_id=entry.test_id,
                qualification_level=entry.qualification_level,
                coverage_status=coverage_status,
                automation_status=entry.automation_status,
                manual_followup_status=entry.manual_followup_status,
                rationale=entry.rationale,
                evidence=entry.evidence,
            )
        )
        if coverage_status == "pending_manual":
            deviations.add(
                test_id=entry.test_id,
                severity="medium",
                ui_area=item.ui_area,
                workflow=entry.workflow,
                ui_object=item.inventory_id,
                step="Traceability matrix coverage review",
                expected="Full automated PQ coverage for discovered UI surface.",
                actual=f"Coverage is {entry.automation_status}; manual/pending follow-up remains.",
                database_path=database_path,
                evidence_path=evidence_path,
                coverage_status=coverage_status,
                recommended_followup=entry.manual_followup_status
                or "Add workflow-specific automated UI qualification.",
                status="pending_manual",
            )
        if not item.has_stable_object_name and item.kind in {"button", "field", "view", "tabs"}:
            deviations.add(
                test_id="UI-PQ-OBJ-001",
                severity="low",
                ui_area=item.ui_area,
                workflow="Stable object naming",
                ui_object=item.inventory_id,
                step="Inspect discovered widget objectName",
                expected="Critical interactive widgets have stable objectName values.",
                actual=(
                    "Widget is discoverable only through fallback text/path: "
                    f"class={item.class_name}; text={item.text!r}; parent={item.parent!r}; "
                    f"path={item.path!r}."
                ),
                database_path=database_path,
                evidence_path=evidence_path,
                coverage_status="object_name_gap",
                recommended_followup="Assign a stable objectName to support precise future UI automation.",
            )
    return rows


def write_traceability_matrix(path: Path, rows: list[TraceabilityRow]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=TRACEABILITY_COLUMNS,
            lineterminator="\n",
        )
        writer.writeheader()
        for row in rows:
            writer.writerow(asdict(row))
    return path
