"""Command-line entrypoint for the canonical QA/PQ impact planner."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from runpy import run_path
from typing import cast


def _planner() -> Callable[..., dict[str, object]]:
    planner_path = Path(__file__).resolve().parents[1] / "isrc_manager" / "qa" / "impact.py"
    definitions = run_path(str(planner_path))
    return cast(Callable[..., dict[str, object]], definitions["plan_qa_pq_impact"])


def _parse_bool(value: str | bool) -> bool:
    if isinstance(value, bool):
        return value
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise argparse.ArgumentTypeError(f"expected a boolean value, got {value!r}")


def _parse_provenance_hash(value: str) -> tuple[str, str]:
    category, separator, digest = value.partition("=")
    if not separator or not category.strip() or not digest.strip():
        raise argparse.ArgumentTypeError("expected CATEGORY=HASH")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", category):
        raise argparse.ArgumentTypeError("provenance category contains unsupported characters")
    return category, digest


def _read_change_records(
    direct_records: Sequence[str], file_names: Sequence[str], read_stdin: bool
) -> list[str]:
    records = list(direct_records)
    stdin_requested = read_stdin
    for file_name in file_names:
        if file_name == "-":
            stdin_requested = True
            continue
        records.extend(Path(file_name).read_text(encoding="utf-8").splitlines())
    if stdin_requested:
        records.extend(sys.stdin.read().splitlines())
    return records


def _write_github_outputs(path: Path, plan: Mapping[str, object]) -> None:
    outputs: dict[str, object] = {
        "artifact_sections": plan["artifact_sections"],
        "dashboard_sections": plan["dashboard_sections"],
        "full_validation": plan["full_validation"],
        "has_pq_work": plan["has_pq_work"],
        "mode": plan["mode"],
        "plan_hash": plan["plan_hash"],
        "plan_json": plan,
        "report_scopes": plan["report_scopes"],
        "screenshot_scopes": plan["screenshot_scopes"],
        "selected_components": plan["selected_components"],
        "test_targets": plan["test_targets"],
    }
    with path.open("a", encoding="utf-8") as output_file:
        for key in sorted(outputs):
            value = outputs[key]
            if isinstance(value, bool):
                serialized = str(value).lower()
            elif isinstance(value, str):
                serialized = value
            else:
                serialized = json.dumps(
                    value, ensure_ascii=False, separators=(",", ":"), sort_keys=True
                )
            output_file.write(f"{key}={serialized}\n")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--changed",
        "--changed-path",
        "--path",
        action="append",
        default=[],
        metavar="PATH_OR_RECORD",
        help="Changed path or git name-status record; repeat for multiple changes.",
    )
    parser.add_argument(
        "--changed-file",
        "--changed-paths-file",
        "--paths-file",
        action="append",
        default=[],
        metavar="FILE",
        help="Read newline-delimited paths/name-status records; use '-' for stdin.",
    )
    parser.add_argument(
        "--stdin", action="store_true", help="Read additional changed-path records from stdin."
    )
    parser.add_argument(
        "--event-type",
        "--event",
        "--event-name",
        default=os.environ.get("GITHUB_EVENT_NAME", "local"),
        help="Event type, such as push, pull_request, schedule, or workflow_dispatch.",
    )
    parser.add_argument(
        "--ref",
        default=os.environ.get("GITHUB_REF", ""),
        help="Git ref; refs/tags/* always requests full validation.",
    )
    parser.add_argument(
        "--full-validation",
        "--manual-full",
        nargs="?",
        const=True,
        default=False,
        type=_parse_bool,
        metavar="BOOL",
        help="Force a full plan (optionally pass true/false from workflow_dispatch).",
    )
    parser.add_argument(
        "--source-commit",
        default=os.environ.get("GITHUB_SHA", ""),
        help="Source commit recorded in provenance metadata.",
    )
    parser.add_argument("--test-version", default="ui-pq-v1")
    parser.add_argument("--renderer-version", default="qa-pq-dashboard-v1")
    parser.add_argument(
        "--provenance-hash",
        action="append",
        default=[],
        type=_parse_provenance_hash,
        metavar="CATEGORY=HASH",
        help="Record a precomputed relevant dependency/configuration hash; repeat as needed.",
    )
    parser.add_argument("--repository-root", type=Path, default=Path.cwd())
    parser.add_argument(
        "--output", type=Path, help="Also write the deterministic JSON plan to this file."
    )
    parser.add_argument(
        "--github-output",
        type=Path,
        help="Append compact workflow outputs to this GitHub Actions output file.",
    )
    parser.add_argument(
        "--compact", action="store_true", help="Print compact rather than indented JSON."
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    records = _read_change_records(args.changed, args.changed_file, args.stdin)
    plan = _planner()(
        records,
        event_type=args.event_type,
        ref=args.ref,
        full_validation=args.full_validation,
        source_commit=args.source_commit,
        test_version=args.test_version,
        renderer_version=args.renderer_version,
        provenance_hashes=dict(args.provenance_hash),
        repository_root=args.repository_root,
    )
    indent = None if args.compact else 2
    serialized = json.dumps(plan, ensure_ascii=False, indent=indent, sort_keys=True) + "\n"
    sys.stdout.write(serialized)
    if args.output is not None:
        args.output.write_text(serialized, encoding="utf-8")
    if args.github_output is not None:
        _write_github_outputs(args.github_output, plan)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
