"""Grouped unittest ownership and CI shard helpers."""

from __future__ import annotations

import argparse
import ast
import sys
from collections import Counter
from functools import lru_cache
from pathlib import Path
from typing import Iterable

BASELINE_TEST_COUNT = 467

GROUP_MODULES: dict[str, tuple[str, ...]] = {
    "catalog-services": (
        "tests.catalog.test_asset_service",
        "tests.catalog.test_contract_service",
        "tests.catalog.test_rights_service",
        "tests.contract_templates.test_catalog",
        "tests.contract_templates.test_export_service",
        "tests.contract_templates.test_form_generation",
        "tests.contract_templates.test_registry_generation",
        "tests.contract_templates.test_revision_service",
        "tests.contract_templates.test_scanner",
        "tests.integration.test_global_search_relationships",
        "tests.integrations.soundcloud.test_soundcloud_coverage_edges",
        "tests.integrations.soundcloud.test_soundcloud_execution_persistence",
        "tests.integrations.soundcloud.test_soundcloud_media",
        "tests.integrations.soundcloud.test_soundcloud_oauth_client",
        "tests.integrations.soundcloud.test_soundcloud_service",
        "tests.invoicing.test_accounting_validation_paths",
        "tests.invoicing.test_invoice_issue_service",
        "tests.invoicing.test_invoice_template_service",
        "tests.invoicing.test_ledger_foundation",
        "tests.invoicing.test_money",
        "tests.invoicing.test_payment_credit_report_service",
        "tests.invoicing.test_royalty_import_service",
        "tests.invoicing.test_royalty_integration_service",
        "tests.invoicing.test_royalty_service",
        "tests.invoicing.test_travel_distance",
        "tests.reporting.test_crash_detection",
        "tests.reporting.test_github_repo_configuration",
        "tests.reporting.test_report_proxy",
        "tests.reporting.test_reporting_pipeline",
        "tests.reporting.test_sanitizer",
        "tests.test_authenticity_manifest_service",
        "tests.test_authenticity_dialogs",
        "tests.test_authenticity_controller",
        "tests.test_authenticity_init",
        "tests.test_authenticity_verification_service",
        "tests.test_audio_conversion_pipeline",
        "tests.test_audio_watermark_service",
        "tests.test_build_requirements",
        "tests.test_assets_service",
        "tests.test_bulk_edit_helpers",
        "tests.test_catalog_admin_service",
        "tests.test_catalog_managers",
        "tests.test_catalog_table_media_routing",
        "tests.test_catalog_read_service",
        "tests.test_catalog_table_controller",
        "tests.test_catalog_table_header_zoom",
        "tests.test_catalog_table_models",
        "tests.test_catalog_table_workflow",
        "tests.test_code_registry_service",
        "tests.test_custom_fields_controller",
        "tests.test_diagnostics_controller",
        "tests.test_diagnostics_report",
        "tests.test_code_registry_workflow_integration",
        "tests.test_contract_controller",
        "tests.test_contract_template_parser",
        "tests.test_contract_template_service",
        "tests.test_conversion_service",
        "tests.test_custom_field_services",
        "tests.test_export_filename_helpers",
        "tests.test_governed_track_creation_service",
        "tests.test_help_content",
        "tests.test_helpers",
        "tests.test_isrc_registry",
        "tests.test_isrc_registry_controller",
        "tests.test_legacy_license_migration_service",
        "tests.test_license_service",
        "tests.test_lightweight_model_edges",
        "tests.test_python_314_compatibility",
        "tests.test_quality_service",
        "tests.test_parties_controller",
        "tests.test_parties_controller_coverage",
        "tests.test_promo_codes_service",
        "tests.test_quality_controller",
        "tests.test_release_controller",
        "tests.test_release_service",
        "tests.test_repertoire_status_service",
        "tests.test_release_automation",
        "tests.test_standard_field_specs",
        "tests.test_sync_version_docs",
        "tests.test_selection_scope",
        "tests.test_tag_service",
        "tests.test_tags_catalog_mapping",
        "tests.test_tags_metadata_controller",
        "tests.test_update_checker",
        "tests.test_update_handoff",
        "tests.test_update_installer",
        "tests.test_updater_helper",
        "tests.test_versioning",
        "tests.test_forensic_watermark_service",
        "tests.test_forensics_controller",
        "tests.test_forensics_service_units",
        "tests.test_forensics_watermark",
        "tests.test_forensics_watermark_coverage",
        "tests.test_track_service",
        "tests.test_work_and_party_services",
    ),
    "exchange-import": (
        "tests.exchange.test_exchange_csv_import",
        "tests.exchange.test_exchange_csv_inspection",
        "tests.exchange.test_exchange_custom_fields",
        "tests.exchange.test_exchange_json",
        "tests.exchange.test_exchange_merge_mode",
        "tests.exchange.test_exchange_normalization",
        "tests.exchange.test_exchange_package",
        "tests.exchange.test_registry_classification",
        "tests.exchange.test_master_transfer",
        "tests.exchange.test_exchange_xlsx_import",
        "tests.exchange.test_exchange_xml_import",
        "tests.test_exchange_controller",
        "tests.test_exchange_repair_queue_controller",
        "tests.test_import_repair_queue",
        "tests.test_master_transfer_controller",
        "tests.test_catalog_xml_controller",
        "tests.exchange.test_repertoire_exchange_service",
        "tests.test_gs1_contract_import_service",
        "tests.test_gs1_excel_export_service",
        "tests.test_gs1_integration_service",
        "tests.test_gs1_repository_service",
        "tests.test_gs1_settings_service",
        "tests.test_gs1_template_service",
        "tests.test_gs1_validation_service",
        "tests.test_party_exchange_service",
        "tests.test_party_import_dialog",
        "tests.test_repertoire_exchange_controller",
        "tests.test_exchange_repair_dialogs",
        "tests.test_xml_export_service",
        "tests.test_xml_import_service",
    ),
    "history-storage-migration": (
        "tests.database.test_schema_current_target",
        "tests.database.test_schema_migrations_10_11",
        "tests.database.test_schema_migrations_35_36",
        "tests.database.test_schema_migrations_36_37",
        "tests.database.test_schema_migrations_37_38",
        "tests.database.test_schema_migrations_38_39",
        "tests.database.test_schema_migrations_39_40",
        "tests.database.test_schema_migrations_12_14",
        "tests.database.test_schema_migrations_20_24",
        "tests.database.test_schema_migrations_25_26",
        "tests.database.test_schema_migrations_27_28",
        "tests.database.test_schema_migrations_28_29",
        "tests.database.test_schema_migrations_29_30",
        "tests.database.test_schema_migrations_30_31",
        "tests.database.test_schema_migrations_31_32",
        "tests.database.test_schema_migrations_32_33",
        "tests.history.test_history_action_helpers",
        "tests.history.test_history_file_effects",
        "tests.history.test_history_recovery",
        "tests.history.test_history_settings",
        "tests.test_history_helpers",
        "tests.test_history_retention_controller_clusters",
        "tests.history.test_history_snapshots",
        "tests.history.test_history_tracks",
        "tests.test_database_admin_service",
        "tests.test_database_security",
        "tests.test_file_storage_helpers",
        "tests.test_db_access",
        "tests.test_history_cleanup_service",
        "tests.test_history_budget_hooks",
        "tests.test_history_dialogs",
        "tests.test_legacy_promoted_field_repair_service",
        "tests.test_migration_integration",
        "tests.test_paths",
        "tests.test_profile_workflow_service",
        "tests.test_profile_session_controller",
        "tests.test_session_history_manager",
        "tests.test_session_service",
        "tests.test_settings_mutations_service",
        "tests.test_settings_read_service",
        "tests.test_settings_transfer_service",
        "tests.test_settings_controller",
        "tests.test_sqlite_utils",
        "tests.test_storage_admin_service",
        "tests.test_storage_migration_service",
        "tests.test_storage_sizes",
        "tests.test_update_preferences",
    ),
    "ui-app-workflows": (
        "tests.app.test_app_shell_catalog_controller",
        "tests.app.test_app_shell_catalog_header_state",
        "tests.app.test_app_shell_catalog_model_view",
        "tests.app.test_app_shell_editor_surfaces",
        "tests.app.test_app_shell_layout_persistence",
        "tests.app.test_app_shell_profiles_and_selection",
        "tests.app.test_app_shell_startup_core",
        "tests.app.test_app_shell_storage_migration_prompts",
        "tests.app.test_app_shell_storage_root_transitions",
        "tests.app.test_app_shell_workspace_docks",
        "tests.catalog.test_contract_dialogs",
        "tests.catalog.test_rights_dialogs",
        "tests.contract_templates.test_dialogs",
        "tests.test_app_bootstrap",
        "tests.test_app_prompts",
        "tests.test_application_settings_gs1",
        "tests.test_app_dialogs",
        "tests.test_app_logging",
        "tests.test_application_settings_dialog_behaviors",
        "tests.test_app_sound_controller",
        "tests.test_background_app_services",
        "tests.test_album_ordering_dialog",
        "tests.test_blob_icons",
        "tests.test_catalog_workspace",
        "tests.test_catalog_workflow_integration",
        "tests.test_code_registry_widgets",
        "tests.test_code_registry_workspace",
        "tests.test_conversion_dialog",
        "tests.test_conversion_dialogs_coverage",
        "tests.test_desktop_safety_probe",
        "tests.test_dialog_controller_behaviors",
        "tests.test_exchange_dialogs",
        "tests.test_external_launch_clusters",
        "tests.test_forensics_dialogs",
        "tests.test_external_launch",
        "tests.test_gs1_dialog",
        "tests.invoicing.test_invoice_workspace_panel",
        "tests.test_main_window_shell_conversion",
        "tests.test_main_window_helpers",
        "tests.test_main_window_layout_helpers",
        "tests.contract_templates.test_workspace_layout_helpers",
        "tests.test_media_conversion_controller",
        "tests.test_media_equalizer",
        "tests.test_media_equalizer_coverage",
        "tests.test_media_equalizer_player",
        "tests.test_media_equalizer_widgets",
        "tests.test_media_export_controller",
        "tests.test_media_player_controller",
        "tests.test_media_preview_preload",
        "tests.test_media_waveform_clusters",
        "tests.test_main_window_shell_settings_transfer",
        "tests.test_public_docs",
        "tests.test_qa_pq_history",
        "tests.test_quality_dialogs",
        "tests.test_promo_codes_dialogs",
        "tests.test_qss_autocomplete",
        "tests.test_qss_reference",
        "tests.test_repertoire_dialogs",
        "tests.test_shortcut_ordering",
        "tests.test_startup_splash",
        "tests.test_tag_dialogs",
        "tests.test_task_manager",
        "tests.test_theme_builder",
        "tests.test_ui_common",
        "tests.test_update_ui_integration",
        "tests.test_update_controller_clusters",
        "tests.test_workspace_debug",
        "tests.integrations.soundcloud.test_ui",
        "tests.tracks.test_edit_dialog_behaviors",
        "tests.test_work_dialogs",
        "tests.test_works_dialogs_coverage",
        "tests.reporting.test_reporting_dialogs_controller",
        "tests.ui_qa.test_qa_helpers",
        "tests.ui_qa.test_ui_pq_accounting_workflow",
        "tests.ui_qa.test_ui_pq_authenticity_workflow",
        "tests.ui_qa.test_ui_pq_catalog_workflow",
        "tests.ui_qa.test_ui_pq_contract_workflow",
        "tests.ui_qa.test_ui_pq_diagnostics_recovery",
        "tests.ui_qa.test_ui_pq_help_documentation",
        "tests.ui_qa.test_ui_pq_import_export",
        "tests.ui_qa.test_ui_pq_inventory",
        "tests.ui_qa.test_ui_pq_media_audio_workflow",
        "tests.ui_qa.test_ui_pq_menus_actions",
        "tests.ui_qa.test_ui_pq_settings_theme_help",
        "tests.ui_qa.test_ui_pq_smoke",
        "tests.ui_qa.test_ui_pq_soundcloud_mock_workflow",
        "tests.ui_qa.test_ui_pq_traceability",
        "tests.ui_qa.test_ui_pq_visual_framework",
        "tests.ui_qa.test_ui_pq_work_release_party_workflow",
    ),
}

TEST_ROOT = Path(__file__).resolve().parent
GROUP_ORDER = tuple(GROUP_MODULES)


def _module_path(module_name: str) -> Path:
    prefix = "tests."
    if not module_name.startswith(prefix):
        raise ValueError(f"Unsupported test module: {module_name}")
    return TEST_ROOT.joinpath(*module_name.removeprefix(prefix).split(".")).with_suffix(".py")


def _module_name(path: Path) -> str:
    relative = path.relative_to(TEST_ROOT).with_suffix("")
    return ".".join(("tests", *relative.parts))


def _discovered_test_files() -> list[Path]:
    return [
        path
        for path in sorted(TEST_ROOT.rglob("test_*.py"))
        if path.is_file() and path.name != "__init__.py"
    ]


def discovered_modules() -> tuple[str, ...]:
    return tuple(_module_name(path) for path in _discovered_test_files())


@lru_cache(maxsize=None)
def _count_tests_in_file(path: Path) -> int:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    count = 0
    for node in tree.body:
        if not isinstance(node, ast.ClassDef):
            continue
        for statement in node.body:
            if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if statement.name.startswith("test_"):
                    count += 1
            elif isinstance(statement, ast.Assign):
                count += sum(
                    1
                    for target in statement.targets
                    if isinstance(target, ast.Name) and target.id.startswith("test_")
                )
            elif isinstance(statement, ast.AnnAssign):
                target = statement.target
                if isinstance(target, ast.Name) and target.id.startswith("test_"):
                    count += 1
    return count


def discovered_test_count() -> int:
    return sum(_count_tests_in_file(path) for path in _discovered_test_files())


def _count_tests_in_modules(modules: Iterable[str]) -> int:
    return sum(_count_tests_in_file(_module_path(module)) for module in modules)


def group_modules(group: str) -> tuple[str, ...]:
    try:
        return GROUP_MODULES[group]
    except KeyError as exc:
        raise KeyError(f"Unknown test group: {group}") from exc


def group_test_count(group: str) -> int:
    return _count_tests_in_modules(group_modules(group))


def verify_grouping() -> list[str]:
    errors: list[str] = []
    discovered = discovered_modules()
    discovered_set = set(discovered)
    grouped_modules = tuple(module for group in GROUP_ORDER for module in GROUP_MODULES[group])
    grouped_set = set(grouped_modules)
    duplicate_modules = sorted(
        module for module, occurrences in Counter(grouped_modules).items() if occurrences > 1
    )
    missing_grouped_modules = sorted(discovered_set - grouped_set)
    stale_group_modules = sorted(grouped_set - discovered_set)
    discovered_count = discovered_test_count()

    if duplicate_modules:
        errors.append("modules assigned to multiple groups: " + ", ".join(duplicate_modules))
    if missing_grouped_modules:
        errors.append("discovered but ungrouped modules: " + ", ".join(missing_grouped_modules))
    if stale_group_modules:
        errors.append("grouped modules missing on disk: " + ", ".join(stale_group_modules))
    if discovered_count < BASELINE_TEST_COUNT:
        errors.append(
            f"discovered test count dropped below baseline: {discovered_count} < {BASELINE_TEST_COUNT}"
        )
    if not stale_group_modules:
        grouped_count = _count_tests_in_modules(grouped_modules)
        if grouped_count != discovered_count:
            errors.append(
                f"grouped test count {grouped_count} does not match discovered count {discovered_count}"
            )

    return errors


def _print_modules(group: str) -> None:
    for module in group_modules(group):
        print(module)


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("group", choices=GROUP_ORDER, help="Test group to inspect or run")
    parser.add_argument(
        "--modules",
        action="store_true",
        help="Print the grouped unittest modules, one per line",
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="Validate the grouping against discovered test files",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)

    if args.verify:
        errors = verify_grouping()
        if errors:
            for error in errors:
                print(f"error: {error}", file=sys.stderr)
            return 1

    if args.modules or not args.verify:
        _print_modules(args.group)

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
