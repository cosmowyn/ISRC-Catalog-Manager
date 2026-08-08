"""Canonical conservative QA/PQ change-impact mapping and planner.

The planner is deliberately independent of Git and GitHub Actions.  Feed it paths from any
change detector and consume its deterministic JSON output locally or in a workflow.
"""

from __future__ import annotations

import hashlib
import json
import posixpath
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from runpy import run_path
from typing import Iterable, Mapping, cast

SCHEMA_VERSION = 1
PLANNER_VERSION = "1"


@dataclass(frozen=True, slots=True)
class ComponentSpec:
    """A separately selectable QA/PQ dashboard component."""

    name: str
    dependencies: tuple[str, ...]
    test_targets: tuple[str, ...]
    dashboard_sections: tuple[str, ...]
    screenshot_scopes: tuple[str, ...]
    report_scopes: tuple[str, ...]
    artifact_sections: tuple[str, ...]
    provenance_inputs: tuple[str, ...]


COMPONENTS: tuple[ComponentSpec, ...] = (
    ComponentSpec(
        name="core-inventory",
        dependencies=(),
        test_targets=(
            "tests/ui_qa/test_ui_pq_inventory.py",
            "tests/ui_qa/test_ui_pq_menus_actions.py",
            "tests/ui_qa/test_ui_pq_smoke.py",
            "tests/ui_qa/test_ui_pq_traceability.py",
        ),
        dashboard_sections=("core", "inventory", "traceability"),
        screenshot_scopes=("main-window", "menus-actions"),
        report_scopes=("evidence-summary", "traceability", "ui-inventory"),
        artifact_sections=("core", "inventory", "traceability"),
        provenance_inputs=(
            "isrc_manager/quality/**",
            "isrc_manager/code_registry/**",
            "isrc_manager/isrc_registry*.py",
            "tests/ui_qa/test_ui_pq_{inventory,menus_actions,smoke,traceability}.py",
        ),
    ),
    ComponentSpec(
        name="visual-help",
        dependencies=("core-inventory",),
        test_targets=(
            "tests/ui_qa/test_ui_pq_help_documentation.py",
            "tests/ui_qa/test_ui_pq_settings_theme_help.py",
        ),
        dashboard_sections=("help-documentation", "visual-help"),
        screenshot_scopes=("help-chapters", "settings-theme-help"),
        report_scopes=("help-coverage", "help-manual"),
        artifact_sections=("help", "visual/help"),
        provenance_inputs=(
            "isrc_manager/help_content.py",
            "isrc_manager/qa/help_validation.py",
            "docs/help/**",
            "tests/ui_qa/test_ui_pq_help_documentation.py",
            "tests/ui_qa/test_ui_pq_settings_theme_help.py",
        ),
    ),
    ComponentSpec(
        name="catalog",
        dependencies=("core-inventory",),
        test_targets=("tests/ui_qa/test_ui_pq_catalog_workflow.py",),
        dashboard_sections=("catalog",),
        screenshot_scopes=("catalog-track-workflow",),
        report_scopes=("catalog-evidence",),
        artifact_sections=("catalog", "visual/catalog"),
        provenance_inputs=(
            "isrc_manager/catalog_table/**",
            "isrc_manager/tracks/**",
            "isrc_manager/tags/**",
            "isrc_manager/catalog_workspace.py",
            "tests/ui_qa/test_ui_pq_catalog_workflow.py",
        ),
    ),
    ComponentSpec(
        name="relationships-releases-parties",
        dependencies=("catalog",),
        test_targets=("tests/ui_qa/test_ui_pq_work_release_party_workflow.py",),
        dashboard_sections=("relationships", "releases", "parties", "repertoire"),
        screenshot_scopes=("work-release-party-workflow",),
        report_scopes=("relationship-evidence",),
        artifact_sections=("relationships", "visual/relationships"),
        provenance_inputs=(
            "isrc_manager/{works,releases,parties,promo_codes}/**",
            "isrc_manager/domain/repertoire.py",
            "tests/ui_qa/test_ui_pq_work_release_party_workflow.py",
        ),
    ),
    ComponentSpec(
        name="contracts-rights",
        dependencies=("relationships-releases-parties",),
        test_targets=("tests/ui_qa/test_ui_pq_contract_workflow.py",),
        dashboard_sections=("contracts", "rights"),
        screenshot_scopes=("contract-rights-workflow",),
        report_scopes=("contract-rights-evidence",),
        artifact_sections=("contracts-rights", "visual/contracts-rights"),
        provenance_inputs=(
            "isrc_manager/{contracts,contract_templates,rights}/**",
            "isrc_manager/services/license*.py",
            "tests/ui_qa/test_ui_pq_contract_workflow.py",
        ),
    ),
    ComponentSpec(
        name="accounting",
        dependencies=("contracts-rights",),
        test_targets=("tests/ui_qa/test_ui_pq_accounting_workflow.py",),
        dashboard_sections=("accounting", "royalties"),
        screenshot_scopes=("accounting-royalties-workflow",),
        report_scopes=("accounting-reports", "royalty-statements"),
        artifact_sections=("accounting", "visual/accounting"),
        provenance_inputs=(
            "isrc_manager/invoicing/**",
            "tests/invoicing/**",
            "tests/ui_qa/test_ui_pq_accounting_workflow.py",
        ),
    ),
    ComponentSpec(
        name="soundcloud",
        dependencies=("contracts-rights", "media-audio"),
        test_targets=("tests/ui_qa/test_ui_pq_soundcloud_mock_workflow.py",),
        dashboard_sections=("soundcloud",),
        screenshot_scopes=("soundcloud-publishing-workflow",),
        report_scopes=("soundcloud-evidence",),
        artifact_sections=("soundcloud", "visual/soundcloud"),
        provenance_inputs=(
            "isrc_manager/integrations/soundcloud/**",
            "tests/integrations/soundcloud/**",
            "tests/ui_qa/test_ui_pq_soundcloud_mock_workflow.py",
        ),
    ),
    ComponentSpec(
        name="diagnostics-history-storage",
        dependencies=("catalog",),
        test_targets=(
            "tests/ui_qa/test_ui_pq_diagnostics_recovery.py",
            "tests/ui_qa/test_ui_pq_history_replay.py",
        ),
        dashboard_sections=("diagnostics", "history", "recovery", "storage"),
        screenshot_scopes=("diagnostics-recovery", "history-replay"),
        report_scopes=("diagnostics-recovery", "history-evidence"),
        artifact_sections=("diagnostics-history-storage", "visual/diagnostics"),
        provenance_inputs=(
            "isrc_manager/{diagnostics,history}/**",
            "isrc_manager/{storage_admin,storage_migration,storage_sizes}.py",
            "isrc_manager/services/{database,db_,profiles,session,settings_,sqlite_}*.py",
            "tests/ui_qa/test_ui_pq_{diagnostics_recovery,history_replay}.py",
        ),
    ),
    ComponentSpec(
        name="imports-exports-reports",
        dependencies=("catalog",),
        test_targets=("tests/ui_qa/test_ui_pq_import_export.py",),
        dashboard_sections=("generated-reports", "imports-exports"),
        screenshot_scopes=("import-export-workflow",),
        report_scopes=("generated-output-manifest", "import-export-evidence"),
        artifact_sections=("imports-exports-reports", "visual/generated-output"),
        provenance_inputs=(
            "isrc_manager/{conversion,exchange,reporting}/**",
            "isrc_manager/services/{exports,gs1_,import}*.py",
            "tests/ui_qa/test_ui_pq_import_export.py",
        ),
    ),
    ComponentSpec(
        name="assets",
        dependencies=("catalog",),
        test_targets=("tests/ui_qa/test_ui_pq_assets_deliverables_workflow.py",),
        dashboard_sections=("assets", "deliverables"),
        screenshot_scopes=("assets-deliverables-workflow",),
        report_scopes=("asset-deliverable-evidence",),
        artifact_sections=("assets", "visual/assets"),
        provenance_inputs=(
            "isrc_manager/assets/**",
            "tests/ui_qa/test_ui_pq_assets_deliverables_workflow.py",
        ),
    ),
    ComponentSpec(
        name="authenticity-forensics",
        dependencies=("media-audio",),
        test_targets=("tests/ui_qa/test_ui_pq_authenticity_workflow.py",),
        dashboard_sections=("authenticity", "forensics"),
        screenshot_scopes=("authenticity-forensics-workflow",),
        report_scopes=("authenticity-manifests", "forensic-ledger"),
        artifact_sections=("authenticity-forensics", "visual/authenticity"),
        provenance_inputs=(
            "isrc_manager/{authenticity,forensics}/**",
            "tests/ui_qa/test_ui_pq_authenticity_workflow.py",
        ),
    ),
    ComponentSpec(
        name="media-audio",
        dependencies=("catalog",),
        test_targets=("tests/ui_qa/test_ui_pq_media_audio_workflow.py",),
        dashboard_sections=("audio", "media"),
        screenshot_scopes=("media-audio-workflow",),
        report_scopes=("media-audio-evidence",),
        artifact_sections=("media-audio", "visual/media"),
        provenance_inputs=(
            "isrc_manager/media/**",
            "isrc_manager/{app_sound_controller,app_sounds}.py",
            "tests/ui_qa/test_ui_pq_media_audio_workflow.py",
        ),
    ),
)

COMPONENT_BY_NAME = {component.name: component for component in COMPONENTS}
ALL_COMPONENT_NAMES = tuple(component.name for component in COMPONENTS)

FULL_ONLY_TEST_TARGETS = (
    "tests/ui_qa/test_qa_helpers.py",
    "tests/ui_qa/test_ui_pq_visual_framework.py",
)

UI_PQ_TEST_COMPONENTS: dict[str, tuple[str, ...]] = {
    test: (component.name,) for component in COMPONENTS for test in component.test_targets
}

_RULES = run_path(str(Path(__file__).with_name("impact_rules.py")))
SHARED_EXACT_PATHS = cast(set[str], _RULES["SHARED_EXACT_PATHS"])
SHARED_PREFIXES = cast(tuple[str, ...], _RULES["SHARED_PREFIXES"])
SHARED_NAME_PREFIXES = cast(tuple[str, ...], _RULES["SHARED_NAME_PREFIXES"])
GENERATED_PREFIXES = cast(tuple[str, ...], _RULES["GENERATED_PREFIXES"])
GENERATED_EXACT_PATHS = cast(set[str], _RULES["GENERATED_EXACT_PATHS"])
HELP_PREFIXES = cast(tuple[str, ...], _RULES["HELP_PREFIXES"])
HELP_EXACT_PATHS = cast(set[str], _RULES["HELP_EXACT_PATHS"])
GLOBAL_UI_SUFFIXES = cast(tuple[str, ...], _RULES["GLOBAL_UI_SUFFIXES"])
DOCUMENTATION_SUFFIXES = cast(tuple[str, ...], _RULES["DOCUMENTATION_SUFFIXES"])
DOCUMENTATION_NAMES = cast(set[str], _RULES["DOCUMENTATION_NAMES"])
SOURCE_PREFIX_COMPONENTS = cast(
    tuple[tuple[str, tuple[str, ...]], ...], _RULES["SOURCE_PREFIX_COMPONENTS"]
)
SOURCE_EXACT_COMPONENTS = cast(dict[str, tuple[str, ...]], _RULES["SOURCE_EXACT_COMPONENTS"])
SERVICE_STEM_COMPONENTS = cast(
    tuple[tuple[tuple[str, ...], tuple[str, ...]], ...],
    _RULES["SERVICE_STEM_COMPONENTS"],
)
TEST_TOKEN_COMPONENTS = cast(
    tuple[tuple[tuple[str, ...], tuple[str, ...]], ...],
    _RULES["TEST_TOKEN_COMPONENTS"],
)
SHARED_PROVENANCE_INPUTS = cast(dict[str, tuple[str, ...]], _RULES["SHARED_PROVENANCE_INPUTS"])

_STATUS_RE = re.compile(r"^(?P<status>[ACDMRTUXB]\d*)[\t ]+(?P<body>.+)$")
_RENAME_BRACE_RE = re.compile(
    r"^(?P<prefix>.*)\{(?P<old>[^{}]*) => (?P<new>[^{}]*)\}(?P<suffix>.*)$"
)


@dataclass(frozen=True, slots=True)
class Change:
    """A normalized changed repository path and its best-known Git status."""

    path: str
    status: str


@dataclass(frozen=True, slots=True)
class PathImpact:
    """The direct impact classification for one normalized path."""

    path: str
    category: str
    components: tuple[str, ...] = ()
    force_full: bool = False


def _sha256_json(value: object) -> str:
    encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def _normalize_path(raw_path: str, repository_root: Path | None) -> str | None:
    value = raw_path.strip().strip('"').replace("\\", "/")
    while value.startswith("./"):
        value = value[2:]
    if not value:
        return None

    if value.startswith("/"):
        if repository_root is None:
            return f"__outside_repository__/{value.lstrip('/')}"
        candidate = Path(value).resolve(strict=False)
        root = repository_root.resolve(strict=False)
        try:
            value = candidate.relative_to(root).as_posix()
        except ValueError:
            return f"__outside_repository__/{candidate.as_posix().lstrip('/')}"

    normalized = posixpath.normpath(value)
    if normalized in {"", "."}:
        return None
    if normalized == ".." or normalized.startswith("../"):
        return f"__outside_repository__/{normalized.removeprefix('../')}"
    return normalized.lstrip("/")


def _expand_arrow_rename(value: str) -> tuple[str, str] | None:
    brace_match = _RENAME_BRACE_RE.fullmatch(value)
    if brace_match is not None:
        prefix = brace_match.group("prefix")
        suffix = brace_match.group("suffix")
        return (
            prefix + brace_match.group("old") + suffix,
            prefix + brace_match.group("new") + suffix,
        )
    if value.count(" => ") == 1:
        old, new = value.split(" => ", maxsplit=1)
        return old, new
    return None


def parse_change_records(
    records: Iterable[str], repository_root: Path | None = None
) -> tuple[tuple[Change, ...], tuple[str, ...]]:
    """Normalize raw paths or ``git diff --name-status`` records.

    Both sides of renames and copies are retained.  Incomplete or ambiguous rename records are
    reported as uncertainties so the resulting plan can force full validation.
    """
    changes: set[Change] = set()
    uncertainties: set[str] = set()

    def add(raw_path: str, status: str) -> None:
        path = _normalize_path(raw_path, repository_root)
        if path is None:
            uncertainties.add("empty-change-path")
            return
        changes.add(Change(path=path, status=status))

    for raw_record in records:
        record = raw_record.rstrip("\r\n")
        if not record.strip():
            continue
        status_match = _STATUS_RE.fullmatch(record)
        if status_match is None:
            arrow = _expand_arrow_rename(record.strip())
            if arrow is None:
                add(record, "unspecified")
            else:
                add(arrow[0], "renamed-from")
                add(arrow[1], "renamed-to")
            continue

        git_status = status_match.group("status")
        status_code = git_status[0]
        body = status_match.group("body")
        if status_code in {"R", "C"}:
            fields = body.split("\t")
            if len(fields) == 2 and all(field.strip() for field in fields):
                add(fields[0], "renamed-from" if status_code == "R" else "copied-from")
                add(fields[1], "renamed-to" if status_code == "R" else "copied-to")
                continue
            arrow = _expand_arrow_rename(body.strip())
            if arrow is not None:
                add(arrow[0], "renamed-from" if status_code == "R" else "copied-from")
                add(arrow[1], "renamed-to" if status_code == "R" else "copied-to")
                continue
            uncertainties.add("incomplete-rename-or-copy-record")
            add(body, "uncertain")
            continue

        status_names = {
            "A": "added",
            "B": "broken-pairing",
            "D": "deleted",
            "M": "modified",
            "T": "type-changed",
            "U": "unmerged",
            "X": "unknown-git-status",
        }
        add(body, status_names.get(status_code, "uncertain"))
        if status_code in {"B", "U", "X"}:
            uncertainties.add("uncertain-git-status")

    return (
        tuple(sorted(changes, key=lambda change: (change.path, change.status))),
        tuple(sorted(uncertainties)),
    )


def _is_documentation(path: str) -> bool:
    name = path.rsplit("/", maxsplit=1)[-1]
    stem = name.split(".", maxsplit=1)[0].upper()
    return (
        path.startswith("docs/")
        or path.lower().endswith(DOCUMENTATION_SUFFIXES)
        or stem in DOCUMENTATION_NAMES
    )


def _component_for_service(path: str) -> tuple[str, ...] | None:
    prefix = "isrc_manager/services/"
    if not path.startswith(prefix) or not path.endswith(".py"):
        return None
    stem = path.removeprefix(prefix).removesuffix(".py")
    for tokens, components in SERVICE_STEM_COMPONENTS:
        if any(stem.startswith(token) for token in tokens):
            return components
    return None


def _components_for_test(path: str) -> tuple[str, ...] | None:
    lowered = path.lower()
    for tokens, components in TEST_TOKEN_COMPONENTS:
        if any(token in lowered for token in tokens):
            return components
    return None


def classify_path(path: str) -> PathImpact:
    """Classify one normalized repository path conservatively."""
    if path.startswith("__outside_repository__/"):
        return PathImpact(path, "uncertain-path", force_full=True)

    if path in SHARED_EXACT_PATHS or path.startswith(SHARED_PREFIXES):
        return PathImpact(path, "shared-infrastructure", force_full=True)
    if path.startswith(SHARED_NAME_PREFIXES):
        return PathImpact(path, "shared-infrastructure", force_full=True)
    if path.lower().endswith(GLOBAL_UI_SUFFIXES):
        return PathImpact(path, "shared-global-ui", force_full=True)
    if path.startswith("isrc_manager/") and path.rsplit("/", maxsplit=1)[-1].endswith(
        "validation.py"
    ):
        return PathImpact(path, "shared-validation-rules", force_full=True)

    if path in HELP_EXACT_PATHS or path.startswith(HELP_PREFIXES):
        return PathImpact(path, "help-content", ("visual-help",))

    if path.startswith("artifacts/ui_pq/visual/baselines/"):
        return PathImpact(path, "shared-screenshot-baseline", force_full=True)
    if path in GENERATED_EXACT_PATHS or path.startswith(GENERATED_PREFIXES):
        return PathImpact(path, "generated-output")

    if _is_documentation(path):
        return PathImpact(path, "documentation")

    explicit_test_components = UI_PQ_TEST_COMPONENTS.get(path)
    if explicit_test_components is not None:
        return PathImpact(path, "component-test", explicit_test_components)

    explicit_source_components = SOURCE_EXACT_COMPONENTS.get(path)
    if explicit_source_components is not None:
        return PathImpact(path, "component-source", explicit_source_components)

    for prefix, components in SOURCE_PREFIX_COMPONENTS:
        if path.startswith(prefix):
            return PathImpact(path, "component-source", components)

    service_components = _component_for_service(path)
    if service_components is not None:
        return PathImpact(path, "component-source", service_components)

    if path.startswith("tests/") and path.endswith(".py"):
        test_components = _components_for_test(path)
        if test_components is not None:
            return PathImpact(path, "component-test", test_components)
        return PathImpact(path, "unknown-test-path", force_full=True)

    if path.startswith("isrc_manager/") or path.endswith(".py"):
        return PathImpact(path, "unknown-production-path", force_full=True)

    if path.startswith(("resources/", "assets/", "icons/")):
        return PathImpact(path, "shared-global-ui", force_full=True)

    if path.startswith(".github/") or path.endswith((".sh", ".toml", ".yaml", ".yml")):
        return PathImpact(path, "shared-infrastructure", force_full=True)

    return PathImpact(path, "unknown-repository-path", force_full=True)


def _dependency_closure(component_names: Iterable[str]) -> set[str]:
    closure = set(component_names)
    pending = list(closure)
    while pending:
        name = pending.pop()
        for dependency in COMPONENT_BY_NAME[name].dependencies:
            if dependency not in closure:
                closure.add(dependency)
                pending.append(dependency)
    return closure


def _collect_component_values(component_names: Iterable[str], attribute: str) -> list[str]:
    values = {
        value for name in component_names for value in getattr(COMPONENT_BY_NAME[name], attribute)
    }
    return sorted(values)


def _mapping_hash() -> str:
    payload = {
        "components": [asdict(component) for component in COMPONENTS],
        "full_only_test_targets": FULL_ONLY_TEST_TARGETS,
        "shared_exact_paths": sorted(SHARED_EXACT_PATHS),
        "shared_prefixes": SHARED_PREFIXES,
        "shared_name_prefixes": SHARED_NAME_PREFIXES,
        "generated_exact_paths": sorted(GENERATED_EXACT_PATHS),
        "generated_prefixes": GENERATED_PREFIXES,
        "help_exact_paths": sorted(HELP_EXACT_PATHS),
        "help_prefixes": HELP_PREFIXES,
        "global_ui_suffixes": GLOBAL_UI_SUFFIXES,
        "documentation_suffixes": DOCUMENTATION_SUFFIXES,
        "documentation_names": sorted(DOCUMENTATION_NAMES),
        "source_exact_components": SOURCE_EXACT_COMPONENTS,
        "source_prefix_components": SOURCE_PREFIX_COMPONENTS,
        "service_stem_components": SERVICE_STEM_COMPONENTS,
        "test_token_components": TEST_TOKEN_COMPONENTS,
        "shared_provenance_inputs": SHARED_PROVENANCE_INPUTS,
    }
    return _sha256_json(payload)


def plan_qa_pq_impact(
    changed_records: Iterable[str],
    *,
    event_type: str = "local",
    ref: str = "",
    full_validation: bool = False,
    source_commit: str = "",
    test_version: str = "ui-pq-v1",
    renderer_version: str = "qa-pq-dashboard-v1",
    provenance_hashes: Mapping[str, str] | None = None,
    repository_root: Path | None = None,
) -> dict[str, object]:
    """Return a deterministic, JSON-serializable QA/PQ impact plan."""
    changes, uncertainties = parse_change_records(changed_records, repository_root)
    changed_paths = sorted({change.path for change in changes})
    impacts = tuple(classify_path(path) for path in changed_paths)

    direct_components = {component for impact in impacts for component in impact.components}
    dependency_components = _dependency_closure(direct_components) - direct_components

    normalized_event = event_type.strip().lower().replace("-", "_")
    normalized_ref = ref.strip()
    reasons: set[str] = set()
    force_full = False

    if full_validation:
        force_full = True
        reasons.add("manual-full-validation")
    if normalized_event in {"schedule", "scheduled"}:
        force_full = True
        reasons.add("scheduled-full-validation")
    if normalized_event in {"release", "release_target"} or normalized_ref.startswith("refs/tags/"):
        force_full = True
        reasons.add("release-full-validation")
    if uncertainties:
        force_full = True
        reasons.add("uncertain-change-input")
    for impact in impacts:
        if impact.force_full:
            force_full = True
            reasons.add(impact.category)
    if not changed_paths and not force_full:
        force_full = True
        reasons.add("no-changed-paths")

    forced_components: set[str]
    if force_full:
        selected_components = set(ALL_COMPONENT_NAMES)
        forced_components = selected_components - direct_components - dependency_components
        mode = "full"
    else:
        selected_components = direct_components | dependency_components
        forced_components = set()
        mode = "incremental" if selected_components else "none"
        reasons.add("component-impact" if selected_components else "no-pq-impact")

    sorted_selected = sorted(selected_components)
    input_categories: dict[str, list[str]] = {}
    for impact in impacts:
        input_categories.setdefault(impact.category, []).append(impact.path)
    input_categories = {
        category: sorted(paths) for category, paths in sorted(input_categories.items())
    }

    component_inputs = {
        name: list(COMPONENT_BY_NAME[name].provenance_inputs) for name in sorted_selected
    }
    supplied_hashes = dict(sorted((provenance_hashes or {}).items()))
    provenance = {
        "source_commit": source_commit,
        "test_version": test_version,
        "renderer_version": renderer_version,
        "mapping_hash": _mapping_hash(),
        "changed_paths_hash": _sha256_json(changed_paths),
        "input_categories": input_categories,
        "input_patterns": {
            "components": component_inputs,
            "shared": {
                category: list(patterns)
                for category, patterns in sorted(SHARED_PROVENANCE_INPUTS.items())
            },
        },
        "supplied_hashes": supplied_hashes,
        "required_output_fields": [
            "source_commit",
            "test_version",
            "renderer_version",
            "relevant_inputs_hash",
            "generated_at",
        ],
    }

    plan: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "planner_version": PLANNER_VERSION,
        "mode": mode,
        "full_validation": force_full,
        "has_pq_work": bool(selected_components),
        "event": {"type": normalized_event, "ref": normalized_ref},
        "changes": [asdict(change) for change in changes],
        "changed_paths": changed_paths,
        "uncertainties": list(uncertainties),
        "path_impacts": [asdict(impact) for impact in impacts],
        "reasons": sorted(reasons),
        "direct_components": sorted(direct_components),
        "dependency_components": sorted(dependency_components),
        "forced_components": sorted(forced_components),
        "selected_components": sorted_selected,
        "test_targets": sorted(
            set(_collect_component_values(sorted_selected, "test_targets"))
            | (set(FULL_ONLY_TEST_TARGETS) if force_full else set())
        ),
        "dashboard_sections": _collect_component_values(sorted_selected, "dashboard_sections"),
        "screenshot_scopes": _collect_component_values(sorted_selected, "screenshot_scopes"),
        "report_scopes": _collect_component_values(sorted_selected, "report_scopes"),
        "artifact_sections": _collect_component_values(sorted_selected, "artifact_sections"),
        "provenance": provenance,
    }
    plan["plan_hash"] = _sha256_json(plan)
    return plan
