"""Grouped unittest ownership and CI shard helpers."""

from __future__ import annotations

import argparse
import ast
import sys
from collections import Counter
from functools import lru_cache
from pathlib import Path
from typing import Iterable

BASELINE_TEST_COUNT = 426

GROUP_MODULES: dict[str, tuple[str, ...]] = {
    "catalog-services": (
        "tests.catalog.test_asset_service",
        "tests.catalog.test_contract_service",
        "tests.catalog.test_rights_service",
        "tests.contract_templates.test_catalog",
        "tests.contract_templates.test_export_service",
        "tests.contract_templates.test_form_generation",
        "tests.contract_templates.test_revision_service",
        "tests.contract_templates.test_scanner",
        "tests.integration.test_global_search_relationships",
        "tests.test_authenticity_manifest_service",
        "tests.test_authenticity_dialogs",
        "tests.test_authenticity_verification_service",
        "tests.test_audio_conversion_pipeline",
        "tests.test_audio_watermark_service",
        "tests.test_build_requirements",
        "tests.test_bulk_edit_helpers",
        "tests.test_catalog_admin_service",
        "tests.test_catalog_read_service",
        "tests.test_contract_template_parser",
        "tests.test_contract_template_service",
        "tests.test_custom_field_services",
        "tests.test_export_filename_helpers",
        "tests.test_governed_track_creation_service",
        "tests.test_help_content",
        "tests.test_helpers",
        "tests.test_legacy_license_migration_service",
        "tests.test_license_service",
        "tests.test_quality_service",
        "tests.test_release_service",
        "tests.test_repertoire_status_service",
        "tests.test_standard_field_specs",
        "tests.test_tag_service",
        "tests.test_forensic_watermark_service",
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
        "tests.exchange.test_master_transfer",
        "tests.exchange.test_exchange_xlsx_import",
        "tests.exchange.test_exchange_xml_import",
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
        "tests.test_xml_export_service",
        "tests.test_xml_import_service",
    ),
    "history-storage-migration": (
        "tests.database.test_schema_current_target",
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
        "tests.history.test_history_snapshots",
        "tests.history.test_history_tracks",
        "tests.test_database_admin_service",
        "tests.test_db_access",
        "tests.test_history_cleanup_service",
        "tests.test_history_dialogs",
        "tests.test_legacy_promoted_field_repair_service",
        "tests.test_migration_integration",
        "tests.test_paths",
        "tests.test_profile_workflow_service",
        "tests.test_session_history_manager",
        "tests.test_session_service",
        "tests.test_settings_mutations_service",
        "tests.test_settings_read_service",
        "tests.test_sqlite_utils",
        "tests.test_storage_admin_service",
        "tests.test_storage_migration_service",
    ),
    "ui-app-workflows": (
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
        "tests.test_app_dialogs",
        "tests.test_background_app_services",
        "tests.test_blob_icons",
        "tests.test_catalog_workspace",
        "tests.test_catalog_workflow_integration",
        "tests.test_desktop_safety_probe",
        "tests.test_dialog_controller_behaviors",
        "tests.test_exchange_dialogs",
        "tests.test_external_launch",
        "tests.test_gs1_dialog",
        "tests.test_public_docs",
        "tests.test_quality_dialogs",
        "tests.test_qss_autocomplete",
        "tests.test_qss_reference",
        "tests.test_repertoire_dialogs",
        "tests.test_startup_splash",
        "tests.test_tag_dialogs",
        "tests.test_task_manager",
        "tests.test_theme_builder",
        "tests.test_ui_common",
        "tests.test_workspace_debug",
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
