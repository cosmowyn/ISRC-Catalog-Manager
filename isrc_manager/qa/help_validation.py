"""Automated Help documentation coverage checks for UI PQ."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from isrc_manager.help_content import (
    HELP_CHAPTERS,
    HELP_SCREENSHOT_REFERENCES,
    HelpChapter,
    help_chapter_screenshot_reference,
    help_screenshot_source_dir,
    render_help_html,
)

from .inventory import UIInventoryItem, normalize_identifier


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        value = str(data or "").strip()
        if value:
            self.parts.append(value)

    def text(self) -> str:
        return " ".join(self.parts)


@dataclass(slots=True)
class HelpCoverageFinding:
    finding_id: str
    severity: str
    category: str
    subject: str
    expected: str
    actual: str
    recommended_update: str


@dataclass(slots=True)
class HelpCoverageReport:
    status: str
    requirement_count: int
    covered_count: int
    coverage_percent: float
    finding_count: int
    screenshot_count: int
    chapter_screenshot_count: int
    chapter_count: int
    chapter_ids: list[str]
    workflow_example_count: int
    findings: list[HelpCoverageFinding]

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["findings"] = [asdict(finding) for finding in self.findings]
        return payload


@dataclass(frozen=True)
class _AreaRequirement:
    ui_area: str
    required_chapters: tuple[str, ...]
    required_terms: tuple[str, ...]


@dataclass(frozen=True)
class _WorkflowRequirement:
    title: str
    required_terms: tuple[str, ...]


_STOPWORDS = {
    "and",
    "are",
    "can",
    "current",
    "file",
    "for",
    "from",
    "into",
    "list",
    "main",
    "menu",
    "new",
    "open",
    "row",
    "selected",
    "show",
    "the",
    "this",
    "until",
    "use",
    "with",
}

_IGNORED_LABELS = {
    "",
    "-",
    "+",
    "?",
    "1",
    "2026",
}

_MONTHS = {
    "january",
    "february",
    "march",
    "april",
    "may",
    "june",
    "july",
    "august",
    "september",
    "october",
    "november",
    "december",
}

_IGNORED_PREFIXES = (
    "qt_",
    "mainwindow_q",
    "scrollleftbutton",
    "scrollrightbutton",
)

_LABEL_ALIASES: dict[str, tuple[str, ...]] = {
    "add_data_work_mode_combo": ("work governance", "link to existing work"),
    "add_data_work_parent_combo": ("work governance", "parent track"),
    "add_data_work_relationship_combo": ("work governance", "relationship type"),
    "add_data_work_work_combo": ("work governance", "existing work"),
    "adddatatabs": ("add track", "work governance"),
    "auto_generation_disabled_until_an_isrc_prefix_is_set": (
        "isrc prefix",
        "generated isrc",
        "application settings",
    ),
    "buma_wnr": ("buma wnr", "work registration number"),
    "catalog": ("catalog table", "catalog workspace"),
    "codes": ("codes", "code registry"),
    "current_scope": ("current scope", "catalog table"),
    "delivery_conversion": ("delivery", "conversion"),
    "governance": ("work governance",),
    "metadata_standards": ("metadata", "standards", "gs1"),
    "parties": ("party manager", "parties"),
    "profile_combo": ("profile selector", "database"),
    "quality_repair": ("quality dashboard", "diagnostics", "repair"),
    "savedlayoutselector": ("saved layouts", "layout"),
    "search_column_combo": ("search controls", "target column"),
    "workspace": ("workspace", "docked"),
}

_AREA_REQUIREMENTS: tuple[_AreaRequirement, ...] = (
    _AreaRequirement(
        "startup_profile",
        ("overview", "main-window", "profiles", "workflow-playbooks"),
        ("profile", "database", "startup", "quality dashboard"),
    ),
    _AreaRequirement(
        "catalog",
        (
            "add-data",
            "album-entry",
            "catalog-table",
            "custom-columns",
            "edit-entry",
            "audio-tags",
            "bulk-audio-attach",
            "workflow-playbooks",
        ),
        ("add track", "add album", "catalog table", "bulk edit", "work governance"),
    ),
    _AreaRequirement(
        "works_releases_parties",
        ("repertoire-knowledge", "releases", "global-search", "workflow-playbooks"),
        ("work manager", "release browser", "party manager", "creator", "split"),
    ),
    _AreaRequirement(
        "contracts_rights",
        ("repertoire-knowledge", "contract-templates", "workflow-playbooks"),
        ("contract manager", "rights matrix", "obligations", "source contract"),
    ),
    _AreaRequirement(
        "accounting_royalties",
        ("accounting-royalties", "workflow-playbooks"),
        ("invoice", "payment", "credit note", "royalty statement", "payout", "ledger"),
    ),
    _AreaRequirement(
        "soundcloud",
        ("soundcloud-publishing", "audio-authenticity", "workflow-playbooks"),
        ("soundcloud", "forensic", "public profile", "private", "preflight"),
    ),
    _AreaRequirement(
        "authenticity",
        ("audio-authenticity", "workflow-playbooks"),
        ("confidence", "sync score", "likely match", "low-confidence", "temporary wav"),
    ),
    _AreaRequirement(
        "import_export",
        ("exchange-formats", "import-workflows", "conversion", "workflow-playbooks"),
        ("dry run", "mapping", "export", "package", "template conversion"),
    ),
    _AreaRequirement(
        "diagnostics",
        ("diagnostics", "history", "application-log", "workflow-playbooks"),
        ("integrity", "repair", "managed files", "history artifacts"),
    ),
    _AreaRequirement(
        "recovery",
        ("history", "diagnostics", "application-storage-admin", "workflow-playbooks"),
        ("backup", "restore", "snapshot", "safe target"),
    ),
    _AreaRequirement(
        "history_recovery",
        ("history", "workflow-playbooks"),
        ("undo", "redo", "snapshot", "restore"),
    ),
    _AreaRequirement(
        "settings_theme_help",
        (
            "settings",
            "theme-settings",
            "layout-action-ribbon",
            "visual-ui-reference",
            "about",
        ),
        ("application settings", "theme", "help contents", "settings export"),
    ),
    _AreaRequirement(
        "media_audio",
        ("media-preview", "bulk-audio-attach", "audio-tags", "workflow-playbooks"),
        ("audio player", "waveform", "media attach", "conversion"),
    ),
    _AreaRequirement(
        "assets_deliverables",
        ("assets-deliverables", "storage-modes", "audio-authenticity"),
        ("asset versions", "deliverables", "derivative ledger", "lineage"),
    ),
    _AreaRequirement(
        "gs1",
        ("gs1-metadata", "workflow-playbooks"),
        ("gs1", "workbook", "template", "export"),
    ),
    _AreaRequirement(
        "code_registry",
        ("code-registry", "workflow-playbooks"),
        ("internal registry", "external identifier", "registry sha-256 key"),
    ),
    _AreaRequirement(
        "search",
        ("global-search", "repertoire-knowledge"),
        ("global search", "relationships", "open record"),
    ),
    _AreaRequirement(
        "logs_support",
        ("application-log", "about", "application-storage-admin"),
        ("application log", "logs folder", "data folder"),
    ),
    _AreaRequirement(
        "reports",
        ("quality-dashboard", "accounting-royalties", "exchange-formats"),
        ("report", "csv", "json", "export"),
    ),
    _AreaRequirement(
        "update_release",
        ("application-updates", "application-log"),
        ("check for updates", "release notes", "updater helper"),
    ),
)

_WORKFLOW_REQUIREMENTS: tuple[_WorkflowRequirement, ...] = (
    _WorkflowRequirement(
        "Create a First Single From Nothing",
        ("before you start", "add track", "work governance", "expected result", "troubleshooting"),
    ),
    _WorkflowRequirement(
        "Build an Album With Release and Work Links",
        ("before you start", "add album", "release browser", "expected result", "troubleshooting"),
    ),
    _WorkflowRequirement(
        "Import, Review, Clean, and Export Catalog Data",
        ("dry run", "data quality dashboard", "template conversion", "expected result"),
    ),
    _WorkflowRequirement(
        "Connect Parties, Works, Contracts, Rights, and Accounting",
        ("party manager", "work manager", "contract manager", "rights matrix", "ledger"),
    ),
    _WorkflowRequirement(
        "Prepare a SoundCloud Upload With a Forensic Trace",
        ("soundcloud", "forensic upload copy", "public profile", "preflight"),
    ),
    _WorkflowRequirement(
        "Verify a Degraded Audio File Honestly",
        ("confidence", "sync score", "likely match", "low-confidence candidate"),
    ),
    _WorkflowRequirement(
        "Recover From a Bad Import or Risky Edit",
        ("undo history", "diagnostics", "restore", "application log"),
    ),
)


def _html_to_text(html_text: str) -> str:
    parser = _TextExtractor()
    parser.feed(html_text)
    return parser.text()


def _normalize_text(value: object) -> str:
    text = str(value or "").replace("&", " and ").replace("…", " ")
    text = re.sub(r"[^a-zA-Z0-9]+", " ", text).strip().lower()
    return re.sub(r"\s+", " ", text)


def _chapter_plain_text(chapter: HelpChapter) -> str:
    parts = [
        chapter.title,
        chapter.summary,
        " ".join(chapter.keywords),
        _html_to_text(chapter.content_html),
    ]
    return _normalize_text(" ".join(parts))


def _corpus_text(chapters: tuple[HelpChapter, ...]) -> str:
    return _normalize_text(" ".join(_chapter_plain_text(chapter) for chapter in chapters))


def _contains_phrase(corpus: str, phrase: str) -> bool:
    return _normalize_text(phrase) in corpus


def _label_for_item(item: UIInventoryItem) -> str:
    return str(item.text or item.object_name or item.inventory_id or "").strip()


def _should_ignore_inventory_label(label: str) -> bool:
    normalized = normalize_identifier(label)
    if normalized in _IGNORED_LABELS or normalized in _MONTHS:
        return True
    if normalized.isdigit():
        return True
    if any(normalized.startswith(prefix) for prefix in _IGNORED_PREFIXES):
        return True
    if normalized in {"table", "qt_spinbox_lineedit"}:
        return True
    return False


def _substantive_tokens(label: str) -> tuple[str, ...]:
    normalized = _normalize_text(label)
    tokens = [
        token
        for token in normalized.split()
        if len(token) >= 3 and token not in _STOPWORDS and not token.isdigit()
    ]
    return tuple(tokens)


def _inventory_label_covered(label: str, corpus: str) -> bool:
    normalized_id = normalize_identifier(label)
    aliases = _LABEL_ALIASES.get(normalized_id)
    if aliases:
        return all(_contains_phrase(corpus, alias) for alias in aliases)
    normalized_label = _normalize_text(label)
    if normalized_label and normalized_label in corpus:
        return True
    tokens = _substantive_tokens(label)
    if not tokens:
        return True
    return all(token in corpus for token in tokens)


def validate_help_coverage(
    inventory: list[UIInventoryItem],
    *,
    chapters: tuple[HelpChapter, ...] = HELP_CHAPTERS,
    screenshot_dir: Path | None = None,
) -> HelpCoverageReport:
    findings: list[HelpCoverageFinding] = []
    requirement_count = 0
    covered_count = 0

    def add_finding(
        *,
        severity: str,
        category: str,
        subject: str,
        expected: str,
        actual: str,
        recommended_update: str,
    ) -> None:
        findings.append(
            HelpCoverageFinding(
                finding_id=f"HELP-COV-{len(findings) + 1:04d}",
                severity=severity,
                category=category,
                subject=subject,
                expected=expected,
                actual=actual,
                recommended_update=recommended_update,
            )
        )

    chapter_map = {chapter.chapter_id: chapter for chapter in chapters}
    corpus = _corpus_text(chapters)

    for requirement in _AREA_REQUIREMENTS:
        if requirement.ui_area not in {item.ui_area for item in inventory}:
            continue
        requirement_count += 1
        missing_chapters = [
            chapter_id
            for chapter_id in requirement.required_chapters
            if chapter_id not in chapter_map
        ]
        missing_terms = [
            term for term in requirement.required_terms if not _contains_phrase(corpus, term)
        ]
        if missing_chapters or missing_terms:
            add_finding(
                severity="high",
                category="ui-area",
                subject=requirement.ui_area,
                expected=(
                    "Help contains required chapters and layman-readable terms for this "
                    "runtime UI area."
                ),
                actual=(
                    f"Missing chapters={missing_chapters or '-'}; "
                    f"missing terms={missing_terms or '-'}."
                ),
                recommended_update=(
                    "Update help_content.py so the UI area has explicit conceptual and "
                    "workflow documentation."
                ),
            )
        else:
            covered_count += 1

    for requirement in _WORKFLOW_REQUIREMENTS:
        requirement_count += 1
        missing_terms = [
            term for term in requirement.required_terms if not _contains_phrase(corpus, term)
        ]
        if missing_terms:
            add_finding(
                severity="high",
                category="workflow-playbook",
                subject=requirement.title,
                expected=(
                    "Workflow playbook includes prerequisites, ordered steps, expected "
                    "result, troubleshooting, and related workflow context."
                ),
                actual=f"Missing required terms={missing_terms}.",
                recommended_update="Expand the Workflow Playbooks chapter for this chain.",
            )
        else:
            covered_count += 1

    for chapter in chapters:
        requirement_count += 1
        word_count = len(_substantive_tokens(_html_to_text(chapter.content_html)))
        if word_count < 90:
            add_finding(
                severity="medium",
                category="chapter-depth",
                subject=chapter.chapter_id,
                expected="Every help chapter has enough explanatory depth for a lay user.",
                actual=f"Chapter has only {word_count} substantive words.",
                recommended_update=(
                    "Expand the chapter with plain-language purpose, steps, outcomes, "
                    "and troubleshooting notes."
                ),
            )
        else:
            covered_count += 1

    seen_inventory_labels: set[str] = set()
    for item in inventory:
        label = _label_for_item(item)
        normalized_label = normalize_identifier(label)
        if normalized_label in seen_inventory_labels or _should_ignore_inventory_label(label):
            continue
        seen_inventory_labels.add(normalized_label)
        requirement_count += 1
        if _inventory_label_covered(label, corpus):
            covered_count += 1
        else:
            add_finding(
                severity="medium",
                category="inventory-label",
                subject=label,
                expected="Every user-facing runtime label is explained or indexed in Help.",
                actual="No matching phrase, alias, or substantive token coverage was found.",
                recommended_update=(
                    "Add the label or a clear explanation of the feature to the relevant "
                    "Help chapter."
                ),
            )

    html_text = render_help_html("Music Catalog Manager")
    screenshot_source = (
        Path(screenshot_dir) if screenshot_dir is not None else help_screenshot_source_dir()
    )
    for reference in HELP_SCREENSHOT_REFERENCES:
        requirement_count += 1
        path = screenshot_source / reference.filename
        if path.exists() and reference.filename in html_text and reference.caption in html_text:
            covered_count += 1
        else:
            add_finding(
                severity="high",
                category="screenshot",
                subject=reference.filename,
                expected=("Help references a real UI screenshot file with a meaningful caption."),
                actual=f"exists={path.exists()}, referenced={reference.filename in html_text}.",
                recommended_update=(
                    "Refresh docs/help/screenshots and keep the Visual UI Reference chapter "
                    "aligned with the current UI."
                ),
            )

    chapter_screenshot_count = 0
    for chapter in chapters:
        reference = help_chapter_screenshot_reference(chapter)
        chapter_screenshot_count += 1
        requirement_count += 1
        path = screenshot_source / reference.filename
        if path.exists() and reference.filename in html_text and reference.caption in html_text:
            covered_count += 1
        else:
            add_finding(
                severity="high",
                category="chapter-screenshot",
                subject=chapter.chapter_id,
                expected=(
                    "Every Help chapter embeds a current UI screenshot generated by "
                    "the Help documentation qualification workflow."
                ),
                actual=f"exists={path.exists()}, referenced={reference.filename in html_text}.",
                recommended_update=(
                    "Run UI PQ to refresh docs/help/screenshots and keep the chapter "
                    "screenshot embedded in the generated Help manual."
                ),
            )

    coverage_percent = (
        round((covered_count / requirement_count) * 100, 2) if requirement_count else 100.0
    )
    status = "passed" if not findings else "failed"
    return HelpCoverageReport(
        status=status,
        requirement_count=requirement_count,
        covered_count=covered_count,
        coverage_percent=coverage_percent,
        finding_count=len(findings),
        screenshot_count=len(HELP_SCREENSHOT_REFERENCES) + chapter_screenshot_count,
        chapter_screenshot_count=chapter_screenshot_count,
        chapter_count=len(chapters),
        chapter_ids=[chapter.chapter_id for chapter in chapters],
        workflow_example_count=len(_WORKFLOW_REQUIREMENTS),
        findings=findings,
    )


def write_help_coverage_report(path: Path, report: HelpCoverageReport) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report.to_dict(), indent=2, sort_keys=True), encoding="utf-8")
    return path
