"""Append a compact QA/PQ dashboard history row."""

from __future__ import annotations

import argparse
import csv
import json
import subprocess
from collections import Counter
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

HISTORY_COLUMNS = (
    "timestamp",
    "source",
    "branch",
    "commit_sha",
    "app_loc",
    "app_loc_delta",
    "total_coverage",
    "statement_coverage",
    "branch_coverage",
    "total_tests",
    "passed_tests",
    "failed_tests",
    "partial_tests",
    "total_deviations",
    "open_deviations",
    "pending_manual_deviations",
    "traceability_rows",
    "traceability_covered",
    "visual_checks_total",
    "visual_checks_failed",
)

DEFAULT_APPLICATION_PATHS = ("ISRC_manager.py", "isrc_manager")
EXCLUDED_APPLICATION_FILES = {Path("isrc_manager/help_content.py")}
EXCLUDED_APPLICATION_DIRS = {Path("isrc_manager/qa")}
PRODUCTION_COVERAGE_ROOT_FILES = {"ISRC_manager.py"}
PRODUCTION_COVERAGE_PREFIXES = ("isrc_manager/",)
EXCLUDED_PRODUCTION_COVERAGE_PREFIXES = (
    "isrc_manager/qa/",
    "tests/",
    "scripts/",
    "docs/",
    "artifacts/",
)
VISUAL_MANIFESTS = (
    "visual/visual_manifest.json",
    "visual/business_workflow_manifest.json",
    "visual/generated_output_manifest.json",
)
DEFAULT_COVERAGE_SNAPSHOT_PATH = Path("docs/validation/coverage_snapshot.json")


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _read_json(path: Path) -> Any:
    if not path.is_file():
        return {} if path.suffix == ".json" else []
    return json.loads(path.read_text(encoding="utf-8"))


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _count_by(rows: Iterable[dict[str, str]], key: str) -> Counter[str]:
    return Counter((row.get(key) or "unknown") for row in rows)


def _format_float(value: object) -> str:
    try:
        return f"{float(value):.4f}"
    except TypeError, ValueError:
        return "0.0000"


def _format_int(value: object) -> str:
    try:
        return str(int(value))
    except TypeError, ValueError:
        return "0"


def _rounded_float(value: object) -> float:
    try:
        return round(float(value), 2)
    except TypeError, ValueError:
        return 0.0


def _git_value(repo_root: Path, args: Sequence[str], default: str = "") -> str:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=repo_root,
            check=True,
            capture_output=True,
            text=True,
        )
    except OSError, subprocess.CalledProcessError:
        return default
    return result.stdout.strip() or default


def _application_files(repo_root: Path) -> list[Path]:
    files: list[Path] = []
    for relative in DEFAULT_APPLICATION_PATHS:
        path = repo_root / relative
        if path.is_file() and path.suffix == ".py":
            files.append(path)
        elif path.is_dir():
            files.extend(sorted(path.rglob("*.py")))
    filtered: list[Path] = []
    for path in files:
        relative = path.relative_to(repo_root)
        if relative in EXCLUDED_APPLICATION_FILES:
            continue
        if any(
            relative == excluded or excluded in relative.parents
            for excluded in EXCLUDED_APPLICATION_DIRS
        ):
            continue
        if "__pycache__" in relative.parts:
            continue
        filtered.append(path)
    return sorted(set(filtered))


def count_application_loc(repo_root: Path) -> int:
    """Count non-empty, non-comment Python lines for runtime app code."""

    total = 0
    for path in _application_files(repo_root):
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith("#"):
                total += 1
    return total


def _last_app_loc(history_path: Path) -> int | None:
    rows = _read_csv(history_path)
    for row in reversed(rows):
        try:
            return int(row.get("app_loc", ""))
        except ValueError:
            continue
    return None


def _visual_counts(pq_artifacts: Path) -> tuple[int, int]:
    total = 0
    failed = 0
    for relative in VISUAL_MANIFESTS:
        manifest = _read_json(pq_artifacts / relative)
        comparisons = manifest.get("comparisons", []) if isinstance(manifest, dict) else []
        total += len(comparisons)
        failed += sum(1 for comparison in comparisons if not comparison.get("passed"))
    return total, failed


def _coverage_display_path(path: str) -> str:
    normalized = path.replace("\\", "/")
    marker = "/isrc_manager/"
    if marker in normalized:
        return f"isrc_manager/{normalized.split(marker, 1)[1]}"
    if normalized.endswith("/ISRC_manager.py"):
        return "ISRC_manager.py"
    return normalized.lstrip("/")


def _is_production_coverage_path(path: str) -> bool:
    display_path = _coverage_display_path(path)
    if any(display_path.startswith(prefix) for prefix in EXCLUDED_PRODUCTION_COVERAGE_PREFIXES):
        return False
    if display_path in PRODUCTION_COVERAGE_ROOT_FILES:
        return True
    return any(display_path.startswith(prefix) for prefix in PRODUCTION_COVERAGE_PREFIXES)


def _summary_int(summary: dict[str, Any], key: str) -> int:
    try:
        return int(summary.get(key) or 0)
    except TypeError, ValueError:
        return 0


def _percent(covered: int, total: int) -> float:
    if total <= 0:
        return 0.0
    return (covered / total) * 100.0


def _collect_production_coverage(
    coverage: dict[str, Any],
) -> tuple[dict[str, float | int], list[dict[str, object]], list[str]]:
    files = coverage.get("files", {}) if isinstance(coverage, dict) else {}
    totals: dict[str, float | int] = {
        "covered_lines": 0,
        "num_statements": 0,
        "missing_lines": 0,
        "covered_branches": 0,
        "num_branches": 0,
        "missing_branches": 0,
        "percent_covered": 0.0,
        "percent_statements_covered": 0.0,
        "percent_branches_covered": 0.0,
    }
    measured_files: list[dict[str, object]] = []
    excluded_files: list[str] = []

    for raw_path, info in files.items():
        display_path = _coverage_display_path(str(raw_path))
        summary = info.get("summary", {}) if isinstance(info, dict) else {}
        statements = _summary_int(summary, "num_statements")
        if statements <= 0:
            continue

        if not _is_production_coverage_path(display_path):
            excluded_files.append(display_path)
            continue

        covered_lines = (
            _summary_int(summary, "covered_lines")
            if "covered_lines" in summary
            else max(0, statements - _summary_int(summary, "missing_lines"))
        )
        missing_lines = (
            _summary_int(summary, "missing_lines")
            if "missing_lines" in summary
            else max(0, statements - covered_lines)
        )
        branches = _summary_int(summary, "num_branches")
        covered_branches = (
            _summary_int(summary, "covered_branches")
            if "covered_branches" in summary
            else max(0, branches - _summary_int(summary, "missing_branches"))
        )
        missing_branches = (
            _summary_int(summary, "missing_branches")
            if "missing_branches" in summary
            else max(0, branches - covered_branches)
        )
        combined_total = statements + branches
        combined_covered = covered_lines + covered_branches

        totals["covered_lines"] = int(totals["covered_lines"]) + covered_lines
        totals["num_statements"] = int(totals["num_statements"]) + statements
        totals["missing_lines"] = int(totals["missing_lines"]) + missing_lines
        totals["covered_branches"] = int(totals["covered_branches"]) + covered_branches
        totals["num_branches"] = int(totals["num_branches"]) + branches
        totals["missing_branches"] = int(totals["missing_branches"]) + missing_branches

        measured_files.append(
            {
                "path": display_path,
                "percent": _rounded_float(_percent(combined_covered, combined_total)),
                "branch": _rounded_float(_percent(covered_branches, branches)),
                "missing": missing_lines,
                "statements": statements,
            }
        )

    covered_lines = int(totals["covered_lines"])
    statements = int(totals["num_statements"])
    covered_branches = int(totals["covered_branches"])
    branches = int(totals["num_branches"])
    totals["percent_covered"] = _percent(covered_lines + covered_branches, statements + branches)
    totals["percent_statements_covered"] = _percent(covered_lines, statements)
    totals["percent_branches_covered"] = _percent(covered_branches, branches)
    return totals, measured_files, sorted(excluded_files)


def collect_coverage_snapshot(coverage_path: Path) -> dict[str, Any]:
    coverage = _read_json(coverage_path)
    totals, measured_files, excluded_files = _collect_production_coverage(coverage)

    lowest_files = sorted(
        measured_files,
        key=lambda row: (float(row["percent"]), -int(row["statements"])),
    )[:12]
    coverage_wins = sorted(
        (row for row in measured_files if float(row["percent"]) >= 95.0),
        key=lambda row: -int(row["statements"]),
    )[:8]

    return {
        "schemaVersion": 1,
        "timestamp": (
            coverage.get("meta", {}).get("timestamp", "") if isinstance(coverage, dict) else ""
        ),
        "linePercent": _rounded_float(totals.get("percent_covered")),
        "statementPercent": _rounded_float(
            totals.get("percent_statements_covered", totals.get("percent_covered"))
        ),
        "branchPercent": _rounded_float(totals.get("percent_branches_covered")),
        "coveredLines": int(totals.get("covered_lines") or 0),
        "statements": int(totals.get("num_statements") or 0),
        "missingLines": int(totals.get("missing_lines") or 0),
        "coveredBranches": int(totals.get("covered_branches") or 0),
        "missingBranches": int(totals.get("missing_branches") or 0),
        "filesMeasured": len(measured_files),
        "filesExcluded": len(excluded_files),
        "excludedFiles": excluded_files[:25],
        "lowestFiles": lowest_files,
        "coverageWins": coverage_wins,
    }


def write_coverage_snapshot(path: Path, snapshot: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(snapshot, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def collect_snapshot(
    *,
    repo_root: Path,
    coverage_path: Path,
    pq_artifacts: Path,
    history_path: Path,
    timestamp: str | None = None,
    source: str = "local",
    branch: str | None = None,
    commit_sha: str | None = None,
) -> dict[str, str]:
    coverage = _read_json(coverage_path)
    totals, _, _ = _collect_production_coverage(coverage)
    events = _read_json(pq_artifacts / "evidence.json")
    if not isinstance(events, list):
        events = []
    event_statuses = Counter(str(event.get("status", "unknown")) for event in events)
    deviations = _read_csv(pq_artifacts / "deviations.csv")
    deviation_statuses = _count_by(deviations, "status")
    traceability = _read_csv(pq_artifacts / "traceability_matrix.csv")
    traceability_statuses = _count_by(traceability, "coverage_status")
    visual_total, visual_failed = _visual_counts(pq_artifacts)
    app_loc = count_application_loc(repo_root)
    previous_loc = _last_app_loc(history_path)
    app_loc_delta = 0 if previous_loc is None else app_loc - previous_loc

    return {
        "timestamp": timestamp or _utc_now(),
        "source": source,
        "branch": branch or _git_value(repo_root, ("rev-parse", "--abbrev-ref", "HEAD")),
        "commit_sha": commit_sha or _git_value(repo_root, ("rev-parse", "HEAD")),
        "app_loc": str(app_loc),
        "app_loc_delta": str(app_loc_delta),
        "total_coverage": _format_float(totals.get("percent_covered")),
        "statement_coverage": _format_float(totals.get("percent_statements_covered")),
        "branch_coverage": _format_float(totals.get("percent_branches_covered")),
        "total_tests": _format_int(len(events)),
        "passed_tests": _format_int(event_statuses.get("passed", 0)),
        "failed_tests": _format_int(event_statuses.get("failed", 0)),
        "partial_tests": _format_int(event_statuses.get("partial", 0)),
        "total_deviations": _format_int(len(deviations)),
        "open_deviations": _format_int(deviation_statuses.get("open", 0)),
        "pending_manual_deviations": _format_int(deviation_statuses.get("pending_manual", 0)),
        "traceability_rows": _format_int(len(traceability)),
        "traceability_covered": _format_int(traceability_statuses.get("covered", 0)),
        "visual_checks_total": _format_int(visual_total),
        "visual_checks_failed": _format_int(visual_failed),
    }


def append_snapshot(history_path: Path, row: dict[str, str]) -> Path:
    history_path.parent.mkdir(parents=True, exist_ok=True)
    should_write_header = not history_path.exists() or history_path.stat().st_size == 0
    with history_path.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=HISTORY_COLUMNS, lineterminator="\n")
        if should_write_header:
            writer.writeheader()
        writer.writerow({column: row.get(column, "") for column in HISTORY_COLUMNS})
    return history_path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--coverage", type=Path, default=Path("coverage.json"))
    parser.add_argument("--pq-artifacts", type=Path, default=Path("artifacts/ui_pq"))
    parser.add_argument(
        "--history",
        type=Path,
        default=Path("docs/validation/qa_pq_history.csv"),
    )
    parser.add_argument(
        "--coverage-snapshot",
        type=Path,
        default=None,
        help="Optional compact dashboard coverage snapshot JSON to write.",
    )
    parser.add_argument("--timestamp")
    parser.add_argument("--source", default="local")
    parser.add_argument("--branch")
    parser.add_argument("--commit-sha")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    repo_root = args.repo_root.resolve()
    coverage_path = args.coverage
    pq_artifacts = args.pq_artifacts
    history_path = args.history
    if not coverage_path.is_absolute():
        coverage_path = repo_root / coverage_path
    if not pq_artifacts.is_absolute():
        pq_artifacts = repo_root / pq_artifacts
    if not history_path.is_absolute():
        history_path = repo_root / history_path
    coverage_snapshot_path = args.coverage_snapshot
    if coverage_snapshot_path is not None and not coverage_snapshot_path.is_absolute():
        coverage_snapshot_path = repo_root / coverage_snapshot_path

    row = collect_snapshot(
        repo_root=repo_root,
        coverage_path=coverage_path,
        pq_artifacts=pq_artifacts,
        history_path=history_path,
        timestamp=args.timestamp,
        source=args.source,
        branch=args.branch,
        commit_sha=args.commit_sha,
    )
    append_snapshot(history_path, row)
    print(f"Appended QA/PQ history row to {history_path}")
    if coverage_snapshot_path is not None:
        write_coverage_snapshot(
            coverage_snapshot_path,
            collect_coverage_snapshot(coverage_path),
        )
        print(f"Wrote QA/PQ coverage snapshot to {coverage_snapshot_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
