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
VISUAL_MANIFESTS = (
    "visual/visual_manifest.json",
    "visual/business_workflow_manifest.json",
    "visual/generated_output_manifest.json",
)


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
    totals = coverage.get("totals", {}) if isinstance(coverage, dict) else {}
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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
