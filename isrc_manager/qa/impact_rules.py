"""Declarative repository-path rules for QA/PQ impact classification."""

from __future__ import annotations

SHARED_EXACT_PATHS = {
    ".coveragerc",
    ".github/dependabot.yml",
    "AGENTS.md",
    "ISRC_manager.py",
    "Makefile",
    "build.py",
    "icon_factory.py",
    "mypy.ini",
    "package-lock.json",
    "Pipfile.lock",
    "poetry.lock",
    "pyproject.toml",
    "pytest.ini",
    "requirements-dev.txt",
    "requirements.txt",
    "setup.cfg",
    "setup.py",
    "tox.ini",
    "uv.lock",
    "isrc_manager/action_ribbon.py",
    "isrc_manager/app_bootstrap.py",
    "isrc_manager/app_dialogs.py",
    "isrc_manager/app_services.py",
    "isrc_manager/constants.py",
    "isrc_manager/file_storage.py",
    "isrc_manager/main_window.py",
    "isrc_manager/main_window_layout.py",
    "isrc_manager/main_window_shell.py",
    "isrc_manager/settings.py",
    "isrc_manager/settings_controller.py",
    "isrc_manager/starter_themes.py",
    "isrc_manager/theme_builder.py",
    "isrc_manager/ui_common.py",
    "isrc_manager/domain/standard_fields.py",
    "isrc_manager/services/database_security.py",
    "isrc_manager/services/db_access.py",
    "isrc_manager/services/profiles.py",
    "isrc_manager/services/schema.py",
    "isrc_manager/services/session.py",
    "isrc_manager/services/settings_mutations.py",
    "isrc_manager/services/settings_reads.py",
    "isrc_manager/services/settings_transfer.py",
    "isrc_manager/services/sqlite_utils.py",
    "scripts/qa_pq_impact.py",
    "scripts/qa_pq_artifacts.py",
    "scripts/qa_pq_fingerprints.py",
    "scripts/qa_pq_provenance.py",
    "scripts/qa_pq_runtime.py",
    "scripts/trusted_ci_artifacts.py",
    "scripts/apply_help_screenshots.py",
    "scripts/update_qa_pq_history.py",
    "tests/ci_groups.py",
    "tests/conftest.py",
    "tests/test_qa_pq_impact.py",
    "tests/test_qa_pq_artifacts.py",
    "tests/test_qa_pq_execution.py",
    "tests/test_trusted_ci_artifacts.py",
    "tests/test_apply_help_screenshots.py",
    "tests/ui_qa/conftest.py",
    "tests/ui_qa/pytest.ini",
    "tests/ui_qa/test_qa_helpers.py",
    "tests/ui_qa/test_ui_pq_visual_framework.py",
    "isrc_manager/qa/impact.py",
    "isrc_manager/qa/impact_rules.py",
}

SHARED_PREFIXES = (
    ".github/actions/",
    ".github/workflows/",
    "isrc_manager/qa/",
)

SHARED_NAME_PREFIXES = (
    "requirements-",
    "isrc_manager/qss_",
)

GENERATED_PREFIXES = (
    "artifacts/ui_pq/",
    "htmlcov/",
)

GENERATED_EXACT_PATHS = {
    ".coverage",
    "coverage.json",
    "coverage.xml",
    "docs/validation/coverage_snapshot.json",
    "docs/validation/qa_pq_history.csv",
}

HELP_PREFIXES = ("docs/help/",)
HELP_EXACT_PATHS = {"isrc_manager/help_content.py"}

GLOBAL_UI_SUFFIXES = (".qss", ".ui")
DOCUMENTATION_SUFFIXES = (".md", ".rst")
DOCUMENTATION_NAMES = {
    "AUTHORS",
    "CHANGELOG",
    "CONTRIBUTING",
    "LICENSE",
    "README",
    "SECURITY",
}

SOURCE_PREFIX_COMPONENTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("isrc_manager/integrations/soundcloud/", ("soundcloud",)),
    ("isrc_manager/invoicing/", ("accounting",)),
    ("isrc_manager/contract_templates/", ("contracts-rights",)),
    ("isrc_manager/contracts/", ("contracts-rights",)),
    ("isrc_manager/rights/", ("contracts-rights",)),
    ("isrc_manager/releases/", ("relationships-releases-parties",)),
    ("isrc_manager/parties/", ("relationships-releases-parties",)),
    ("isrc_manager/works/", ("relationships-releases-parties",)),
    ("isrc_manager/promo_codes/", ("relationships-releases-parties",)),
    ("isrc_manager/authenticity/", ("authenticity-forensics",)),
    ("isrc_manager/forensics/", ("authenticity-forensics",)),
    ("isrc_manager/assets/", ("assets",)),
    ("isrc_manager/media/", ("media-audio",)),
    ("isrc_manager/diagnostics/", ("diagnostics-history-storage",)),
    ("isrc_manager/history/", ("diagnostics-history-storage",)),
    ("isrc_manager/conversion/", ("imports-exports-reports",)),
    ("isrc_manager/exchange/", ("imports-exports-reports",)),
    ("isrc_manager/reporting/", ("imports-exports-reports",)),
    ("isrc_manager/catalog_table/", ("catalog",)),
    ("isrc_manager/tracks/", ("catalog",)),
    ("isrc_manager/tags/", ("catalog",)),
    ("isrc_manager/quality/", ("core-inventory",)),
    ("isrc_manager/code_registry/", ("core-inventory",)),
)

SOURCE_EXACT_COMPONENTS: dict[str, tuple[str, ...]] = {
    "isrc_manager/app_sound_controller.py": ("media-audio",),
    "isrc_manager/app_sounds.py": ("media-audio",),
    "isrc_manager/catalog_managers.py": ("catalog",),
    "isrc_manager/catalog_workspace.py": ("catalog",),
    "isrc_manager/file_storage.py": ("diagnostics-history-storage",),
    "isrc_manager/gs1_dialog.py": ("imports-exports-reports",),
    "isrc_manager/history_retention_controller.py": ("diagnostics-history-storage",),
    "isrc_manager/import_review_dialog.py": ("imports-exports-reports",),
    "isrc_manager/isrc_registry.py": ("core-inventory",),
    "isrc_manager/isrc_registry_controller.py": ("core-inventory",),
    "isrc_manager/profile_session.py": ("diagnostics-history-storage",),
    "isrc_manager/selection_scope.py": ("catalog",),
    "isrc_manager/storage_admin.py": ("diagnostics-history-storage",),
    "isrc_manager/storage_migration.py": ("diagnostics-history-storage",),
    "isrc_manager/storage_sizes.py": ("diagnostics-history-storage",),
}

SERVICE_STEM_COMPONENTS: tuple[tuple[tuple[str, ...], tuple[str, ...]], ...] = (
    (("license",), ("contracts-rights",)),
    (("repertoire", "track_artist"), ("relationships-releases-parties",)),
    (("export", "gs1_", "import"), ("imports-exports-reports",)),
    (("catalog", "bulk_edit", "custom_field", "track"), ("catalog",)),
    (
        ("database", "db_", "profile", "session", "settings", "sqlite"),
        ("diagnostics-history-storage",),
    ),
)

TEST_TOKEN_COMPONENTS: tuple[tuple[tuple[str, ...], tuple[str, ...]], ...] = (
    (("soundcloud",), ("soundcloud",)),
    (
        ("accounting", "credit_note", "invoice", "ledger", "money", "royalt", "payment"),
        ("accounting",),
    ),
    (("contract", "right", "license"), ("contracts-rights",)),
    (
        ("release", "part", "repertoire", "promo", "work_", "works"),
        ("relationships-releases-parties",),
    ),
    (("authentic", "forensic", "watermark"), ("authenticity-forensics",)),
    (("asset", "deliverable"), ("assets",)),
    (("media", "audio", "equalizer", "waveform", "bookmark"), ("media-audio",)),
    (
        ("diagnostic", "history", "storage", "database", "profile", "session", "sqlite"),
        ("diagnostics-history-storage",),
    ),
    (("exchange", "export", "gs1", "import", "report", "conversion"), ("imports-exports-reports",)),
    (("catalog", "track", "tag", "registry", "quality", "selection", "custom_field"), ("catalog",)),
)

SHARED_PROVENANCE_INPUTS: dict[str, tuple[str, ...]] = {
    "build-dependencies": (
        "pyproject.toml",
        "requirements.txt",
        "requirements-dev.txt",
    ),
    "dashboard-renderer": (
        "scripts/update_qa_pq_history.py",
        "isrc_manager/qa/evidence.py",
        "isrc_manager/qa/traceability.py",
        "isrc_manager/qa/visual.py",
    ),
    "qa-harness": (
        "isrc_manager/qa/**",
        "tests/ui_qa/conftest.py",
        "tests/ui_qa/pytest.ini",
    ),
    "workflow": (".github/workflows/ci.yml", ".github/workflows/help-docs-refresh.yml"),
}
