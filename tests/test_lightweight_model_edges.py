import sqlite3
from pathlib import Path

from isrc_manager.authenticity.models import (
    AuthenticityExportPlan,
    AuthenticityExportPlanItem,
    AuthenticityExportResult,
    AuthenticityKeyRecord,
    AuthenticityManifestRecord,
    AuthenticityVerificationReport,
    PreparedAuthenticityManifest,
    ReferenceAudioSelection,
    WatermarkExtractionResult,
    WatermarkToken,
)
from isrc_manager.code_registry.models import (
    CodeIdentifierClassification,
    CodeIdentifierResolution,
    CodeRegistryAssignmentTarget,
    CodeRegistryCategoryRecord,
    CodeRegistryChoice,
    CodeRegistryEntryGenerationResult,
    CodeRegistryEntryRecord,
    CodeRegistryUsageLink,
    ExternalCodeIdentifierRecord,
)
from isrc_manager.contract_templates.models import (
    ContractTemplateCatalogEntry,
    ContractTemplateExportResult,
    ContractTemplateFormAutoField,
    ContractTemplateFormChoice,
    ContractTemplateFormDefinition,
    ContractTemplateFormManualField,
    ContractTemplateFormSelectorField,
    ContractTemplateOutputArtifactRecord,
    ContractTemplateResolvedSnapshotRecord,
    build_contract_template_indexed_selection_key,
    build_contract_template_selector_scope_key,
)
from isrc_manager.domain.codes import (
    barcode_validation_status,
    is_valid_isrc_compact_or_iso,
    is_valid_iswc_any,
    normalize_isrc,
    normalize_iswc,
    to_iso_isrc,
    to_iso_iswc,
    upc_ean_checksum_valid,
    valid_upc_ean,
)
from isrc_manager.exchange.models import (
    ExchangeIdentifierClassificationOutcome,
    ExchangeImportReport,
)
from isrc_manager.services.track_artist_sql import (
    table_columns,
    track_additional_artists_expr,
    track_main_artist_join_sql,
)
from isrc_manager.storage_sizes import (
    bytes_to_megabytes_floor,
    format_storage_bytes,
    parse_storage_text_to_megabytes,
    storage_text_is_valid,
)


def test_registry_model_to_dict_serializes_nested_generation_result() -> None:
    category = CodeRegistryCategoryRecord(
        id=1,
        system_key="invoice_number",
        display_name="Invoice Number",
        subject_kind="invoice",
        generation_strategy="sequential",
        prefix="INV",
        normalized_prefix="INV",
        active_flag=True,
        sort_order=1,
        is_system=True,
        created_at="2026-06-01",
        updated_at=None,
    )
    entry = CodeRegistryEntryRecord(
        id=2,
        category_id=1,
        category_system_key="invoice_number",
        category_display_name="Invoice Number",
        subject_kind="invoice",
        generation_strategy="sequential",
        value="INV-1",
        normalized_value="INV1",
        entry_kind="generated",
        prefix_snapshot="INV",
        sequence_year=2026,
        sequence_number=1,
        immutable_flag=True,
        created_at="2026-06-01",
        created_via="test",
        notes=None,
    )

    assert category.to_dict()["display_name"] == "Invoice Number"
    assert entry.to_dict()["value"] == "INV-1"
    assert (
        ExternalCodeIdentifierRecord(
            id=3,
            category_system_key="catalog_number",
            value="CAT-1",
            normalized_value="CAT1",
            origin_record_kind="track",
            origin_record_id=9,
            provenance_kind="import",
            classification_status="external",
            classification_reason="manual",
            source_label="CSV",
            matched_registry_entry_id=None,
            created_at=None,
            updated_at=None,
        ).to_dict()["source_label"]
        == "CSV"
    )
    assert CodeRegistryUsageLink("invoice", 4, "Invoice", "number").to_dict()["subject_id"] == 4
    assert CodeRegistryAssignmentTarget("invoice", 4, "Invoice").to_dict()["label"] == "Invoice"
    assert CodeRegistryChoice(2, 1, "Invoice", "INV-1", "INV-1").to_dict()["entry_id"] == 2
    assert CodeIdentifierResolution("internal", value="INV-1").to_dict()["value"] == "INV-1"
    assert (
        CodeIdentifierClassification("INV-1", "INV1", "internal").to_dict()["classification"]
        == "internal"
    )
    assert CodeRegistryEntryGenerationResult(entry, category).to_dict()["category"]["id"] == 1


def test_exchange_import_report_identifier_totals_and_catalog_filter() -> None:
    catalog_key = "catalog_number"
    report = ExchangeImportReport(
        format_name="CSV",
        mode="dry_run",
        passed=1,
        failed=0,
        skipped=0,
        warnings=[],
        duplicates=[],
        unknown_fields=[],
        identifier_totals={
            catalog_key: {
                "internal": 2,
                "external": 3,
                "mismatch": 4,
                "skipped": 5,
                "merged": 6,
                "conflicted": 7,
            },
            "invoice_number": {"internal": 11, "external": 13},
        },
        identifier_classifications=[
            ExchangeIdentifierClassificationOutcome(
                1,
                "Catalog Number",
                catalog_key,
                "CAT-1",
                "internal",
                "linked",
            ),
            ExchangeIdentifierClassificationOutcome(
                2,
                "Invoice Number",
                "invoice_number",
                "INV-1",
                "external",
                "review",
            ),
        ],
    )

    assert report.internal_identifiers == 13
    assert report.external_identifiers == 16
    assert report.mismatched_identifiers == 4
    assert report.skipped_identifiers == 5
    assert report.merged_identifiers == 6
    assert report.conflicted_identifiers == 7
    assert report.internal_catalog_identifiers == 2
    assert report.external_catalog_identifiers == 3
    assert report.mismatched_catalog_identifiers == 4
    assert report.skipped_catalog_identifiers == 5
    assert report.merged_catalog_identifiers == 6
    assert report.conflicted_catalog_identifiers == 7
    assert [item.value for item in report.catalog_classifications] == ["CAT-1"]


def test_track_artist_sql_handles_missing_party_and_legacy_artist_authority() -> None:
    conn = sqlite3.connect(":memory:")
    try:
        assert table_columns(conn, "Tracks") == set()
        assert track_main_artist_join_sql(conn) == ("", "''")
        assert track_additional_artists_expr(conn) == "''"

        conn.execute("CREATE TABLE Tracks(id INTEGER PRIMARY KEY, main_artist_id INTEGER)")
        conn.execute("CREATE TABLE Artists(id INTEGER PRIMARY KEY, name TEXT)")
        conn.execute("CREATE TABLE TrackArtists(track_id INTEGER, artist_id INTEGER, role TEXT)")
        join_sql, display_sql = track_main_artist_join_sql(conn)
        additional_sql = track_additional_artists_expr(conn, separator=" / ")
    finally:
        conn.close()

    assert "LEFT JOIN Artists" in join_sql
    assert "artist_record.name" in display_sql
    assert "JOIN Artists" in additional_sql
    assert "' / '" in additional_sql


def test_code_and_storage_helpers_cover_invalid_and_boundary_inputs() -> None:
    assert normalize_isrc(None) == ""
    assert to_iso_isrc("bad") == ""
    assert is_valid_isrc_compact_or_iso("") is False
    assert normalize_iswc(None) == ""
    assert to_iso_iswc("T12") == ""
    assert to_iso_iswc("T123456789Z") == ""
    assert is_valid_iswc_any("") is True
    assert valid_upc_ean("") is True
    assert upc_ean_checksum_valid("abc") is False
    assert barcode_validation_status("") == "missing"
    assert barcode_validation_status("abc") == "invalid_format"
    assert barcode_validation_status("123456789013") == "invalid_checksum"

    assert bytes_to_megabytes_floor(-1) == 0
    assert format_storage_bytes(-1) == "0 B"
    assert format_storage_bytes(1024, max_decimals=0) == "1 KB"
    assert parse_storage_text_to_megabytes("1g") == 1024
    assert parse_storage_text_to_megabytes("1t") == 1048576
    assert storage_text_is_valid("nonsense") is False


def test_authenticity_model_serialization_sanitises_bytes_and_nested_tokens() -> None:
    token = WatermarkToken(version=1, watermark_id=9, manifest_digest_prefix="abc", nonce=4)
    reference = ReferenceAudioSelection(
        track_id=1,
        source_kind="file",
        source_label="Master",
        reference_asset_id=None,
        filename="master.wav",
        mime_type="audio/wav",
        size_bytes=4,
        suffix=".wav",
        source_path=Path("/tmp/master.wav"),
        source_bytes=b"1234",
    )
    manifest = PreparedAuthenticityManifest(
        track_id=1,
        track_title="Track",
        suggested_name="Track",
        key_id="key",
        signer_label="Signer",
        public_key_b64="public",
        payload={"track": 1},
        payload_canonical="{}",
        payload_sha256="sha",
        signature_b64="sig",
        watermark_token=token,
        reference=reference,
        embed_settings={},
    )
    plan = AuthenticityExportPlan(
        key_id="key",
        signer_label="Signer",
        items=[
            AuthenticityExportPlanItem(1, "Ready", "file", ".wav", "Ready", "key"),
            AuthenticityExportPlanItem(2, "Skip", "file", ".mp3", "Skip", "key", status="warning"),
        ],
        warnings=["lossy"],
    )

    assert (
        AuthenticityKeyRecord("key", "ed25519", "Signer", "pub", None, None, None).to_dict()[
            "key_id"
        ]
        == "key"
    )
    assert (
        AuthenticityManifestRecord(
            1,
            1,
            None,
            "key",
            1,
            1,
            "manifest",
            9,
            4,
            "abc",
            "{}",
            "sha",
            "sig",
            "audio-sha",
            "fingerprint",
            "file",
            None,
            None,
            None,
        ).to_dict()["manifest_id"]
        == "manifest"
    )
    assert reference.to_dict()["source_bytes"] == "<4 bytes>"
    assert manifest.to_dict()["watermark_token"]["watermark_id"] == 9
    assert [item.track_title for item in plan.ready_items()] == ["Ready"]
    assert plan.to_dict()["warnings"] == ["lossy"]
    assert (
        AuthenticityExportResult(2, 1, 1, [], ["a.wav"], ["a.json"], ["m"]).to_dict()["exported"]
        == 1
    )
    assert (
        WatermarkExtractionResult("ok", "key", token, 0.9, 0.8, 0.7, 4, True).to_dict()["token"][
            "nonce"
        ]
        == 4
    )
    assert (
        WatermarkExtractionResult("missing", None, None, 0, 0, 0, 0, False).to_dict()["token"]
        is None
    )
    assert (
        AuthenticityVerificationReport("ok", "verified", "file.wav").to_dict()["inspected_path"]
        == "file.wav"
    )


def test_contract_template_model_serialization_and_source_kind_edges() -> None:
    duplicate = ContractTemplateCatalogEntry(
        binding_kind="duplicate",
        namespace=None,
        key="number",
        canonical_symbol="{{duplicate.number}}",
        display_label="Duplicate count",
        field_type="number",
        description=None,
        scope_entity_type=None,
        scope_policy=None,
        source_table=None,
        source_column=None,
    )
    custom = ContractTemplateCatalogEntry(
        binding_kind="db",
        namespace="track",
        key="mood",
        canonical_symbol="{{db.track.mood}}",
        display_label="Mood",
        field_type="text",
        description=None,
        scope_entity_type=None,
        scope_policy=None,
        source_table="Tracks",
        source_column="mood",
        custom_field_id=3,
        is_custom_field=True,
    )
    owner = ContractTemplateCatalogEntry(
        binding_kind="settings",
        namespace="owner",
        key="name",
        canonical_symbol="{{settings.owner.name}}",
        display_label="Owner",
        field_type="text",
        description=None,
        scope_entity_type=None,
        scope_policy=None,
        source_table=None,
        source_column=None,
        is_settings_field=True,
    )
    app_setting = ContractTemplateCatalogEntry(
        binding_kind="settings",
        namespace="app",
        key="currency",
        canonical_symbol="{{settings.app.currency}}",
        display_label="Currency",
        field_type="text",
        description=None,
        scope_entity_type=None,
        scope_policy=None,
        source_table=None,
        source_column=None,
        is_settings_field=True,
    )
    choice = ContractTemplateFormChoice("a", "A", "Choice A")
    selector = ContractTemplateFormSelectorField(
        "db_scope.party.selection_required",
        "Party",
        "party",
        "selection_required",
        "combo",
        True,
        ("{{db.party.name}}",),
        (choice,),
    )
    auto = ContractTemplateFormAutoField("{{current.date}}", "Date", "Automatic", True, 1)
    manual = ContractTemplateFormManualField(
        "{{manual.note}}", "Note", "text", "line_edit", False, 2, options=("x", "y")
    )
    definition = ContractTemplateFormDefinition(
        1,
        2,
        "Template",
        "v1",
        "scan_ok",
        (auto,),
        (selector,),
        (manual,),
        indexed_selector_fields=(selector,),
        indexed_manual_fields=(manual,),
        unresolved_placeholders=("{{missing}}",),
        warnings=("warn",),
    )
    snapshot = ContractTemplateResolvedSnapshotRecord(
        1,
        2,
        3,
        "party",
        "4",
        {"a": "b"},
        [],
        {},
        "sha",
        "2026-06-01",
    )
    artifact = ContractTemplateOutputArtifactRecord(
        1,
        1,
        "pdf",
        "generated",
        "/tmp/out.pdf",
        "out.pdf",
        "application/pdf",
        12,
        "sha",
        True,
        "2026-06-01",
    )
    export = ContractTemplateExportResult(snapshot, None, artifact, artifact, ("warn",))

    assert build_contract_template_selector_scope_key(" Party ", None) == (
        "db_scope.party.selection_required"
    )
    assert build_contract_template_selector_scope_key("", "x") is None
    assert build_contract_template_indexed_selection_key("{{db.party.name}}", 0).endswith(
        "#index:1"
    )
    assert duplicate.source_kind == "Template Control"
    assert custom.source_kind == "Custom Field"
    assert owner.source_kind == "Owner Party"
    assert app_setting.source_kind == "Application Settings"
    assert duplicate.to_dict()["canonical_symbol"] == "{{duplicate.number}}"
    assert definition.to_dict()["manual_fields"][0]["options"] == ["x", "y"]
    assert export.to_dict()["resolved_docx_artifact"] is None
    assert export.to_dict()["resolved_html_artifact"]["output_filename"] == "out.pdf"
