from pathlib import Path

from scripts.configure_github_reporting import (
    REPORTING_LABELS,
    label_payload,
    repository_parts,
    validate_label_configs,
)


def test_reporting_label_configuration_matches_issue_forms() -> None:
    validate_label_configs(REPORTING_LABELS)
    names = {label.name for label in REPORTING_LABELS}

    assert {"bug", "user-report", "crash-report"} <= names
    for label in REPORTING_LABELS:
        payload = label_payload(label)
        assert payload["name"] == label.name
        assert len(payload["color"]) == 6
        assert payload["description"]


def test_issue_templates_reference_configured_labels() -> None:
    issue_template_dir = Path(".github/ISSUE_TEMPLATE")
    bug_template = (issue_template_dir / "bug_report.yml").read_text(encoding="utf-8")
    crash_template = (issue_template_dir / "crash_report.yml").read_text(encoding="utf-8")
    configured_labels = {label.name for label in REPORTING_LABELS}

    assert "blank_issues_enabled: false" in (issue_template_dir / "config.yml").read_text(
        encoding="utf-8"
    )
    assert all(label in bug_template for label in {"bug", "user-report"})
    assert all(label in crash_template for label in {"bug", "user-report", "crash-report"})
    assert {"bug", "user-report", "crash-report"} <= configured_labels


def test_repository_parts_requires_owner_name_form() -> None:
    assert repository_parts("cosmowyn/ISRC-Catalog-Manager") == (
        "cosmowyn",
        "ISRC-Catalog-Manager",
    )
