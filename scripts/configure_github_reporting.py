"""Configure GitHub labels required by the report proxy and issue forms.

This script intentionally reads credentials from the environment only. It does not write or store
GitHub tokens.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from typing import Any

DEFAULT_REPOSITORY = "cosmowyn/ISRC-Catalog-Manager"


@dataclass(frozen=True)
class ReportingLabel:
    name: str
    color: str
    description: str


REPORTING_LABELS: tuple[ReportingLabel, ...] = (
    ReportingLabel(
        name="bug",
        color="d73a4a",
        description="Confirmed or suspected product defect.",
    ),
    ReportingLabel(
        name="user-report",
        color="0e8a16",
        description="Issue created from a user-supplied report or app-generated report preview.",
    ),
    ReportingLabel(
        name="crash-report",
        color="b60205",
        description="Unexpected application termination report generated after restart.",
    ),
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=DEFAULT_REPOSITORY, help="Repository in owner/name form.")
    parser.add_argument(
        "--api-base",
        default="https://api.github.com",
        help="GitHub API base URL.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the required label payloads without contacting GitHub.",
    )
    args = parser.parse_args(argv)

    validate_label_configs(REPORTING_LABELS)
    if args.dry_run:
        print(json.dumps([label_payload(label) for label in REPORTING_LABELS], indent=2))
        return 0

    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if not token:
        raise SystemExit(
            "Set GH_TOKEN or GITHUB_TOKEN with repository label administration access."
        )

    actions = sync_reporting_labels(
        repository=args.repo,
        token=token,
        api_base=args.api_base,
    )
    for action in actions:
        print(action)
    return 0


def validate_label_configs(labels: tuple[ReportingLabel, ...]) -> None:
    seen: set[str] = set()
    for label in labels:
        if label.name in seen:
            raise ValueError(f"Duplicate label name: {label.name}")
        seen.add(label.name)
        if not re.fullmatch(r"[0-9a-fA-F]{6}", label.color):
            raise ValueError(f"Label {label.name!r} has invalid color {label.color!r}")
        if not label.description:
            raise ValueError(f"Label {label.name!r} must have a description")


def label_payload(label: ReportingLabel) -> dict[str, str]:
    return asdict(label)


def sync_reporting_labels(
    *,
    repository: str,
    token: str,
    api_base: str = "https://api.github.com",
) -> list[str]:
    owner, repo = repository_parts(repository)
    actions: list[str] = []
    for label in REPORTING_LABELS:
        escaped_name = urllib.parse.quote(label.name, safe="")
        label_url = f"{api_base.rstrip('/')}/repos/{owner}/{repo}/labels/{escaped_name}"
        create_url = f"{api_base.rstrip('/')}/repos/{owner}/{repo}/labels"
        payload = label_payload(label)
        try:
            _github_request("GET", label_url, token=token)
        except urllib.error.HTTPError as exc:
            if exc.code != 404:
                raise
            _github_request("POST", create_url, token=token, payload=payload)
            actions.append(f"created {label.name}")
            continue
        _github_request("PATCH", label_url, token=token, payload=payload)
        actions.append(f"updated {label.name}")
    return actions


def repository_parts(repository: str) -> tuple[str, str]:
    parts = repository.strip().split("/", maxsplit=1)
    if len(parts) != 2 or not all(parts):
        raise ValueError("Repository must be in owner/name form.")
    return parts[0], parts[1]


def _github_request(
    method: str,
    url: str,
    *,
    token: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    body = None if payload is None else json.dumps(payload, sort_keys=True).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        method=method,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "ISRC-Catalog-Manager-Reporting-Config",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        raw = response.read()
    if not raw:
        return {}
    parsed = json.loads(raw.decode("utf-8"))
    return parsed if isinstance(parsed, dict) else {}


if __name__ == "__main__":
    sys.exit(main())
