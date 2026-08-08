"""Validated GitHub REST transport for build cleanup automation."""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Iterable

PER_PAGE = 100
_NOT_FOUND = object()


class GitHubApi:
    """Small GitHub REST client with fail-closed collection validation."""

    def __init__(self, repository: str, token: str, api_url: str, timeout: float = 30.0):
        parts = repository.split("/")
        if len(parts) != 2 or not all(re.fullmatch(r"[A-Za-z0-9_.-]+", part) for part in parts):
            raise ValueError("repository must have the form owner/name")
        self.repository = "/".join(urllib.parse.quote(part, safe="") for part in parts)
        self.token = token
        self.api_url = api_url.rstrip("/")
        self.timeout = timeout

    def request(self, method: str, path: str, *, allow_not_found: bool = False) -> Any:
        request = urllib.request.Request(
            f"{self.api_url}{path}",
            method=method,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self.token}",
                "User-Agent": "isrc-catalog-manager-cleanup",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                body = response.read()
        except urllib.error.HTTPError as exc:
            if allow_not_found and exc.code == 404:
                return _NOT_FOUND
            detail = exc.read().decode("utf-8", errors="replace")[:500]
            raise RuntimeError(
                f"GitHub API {method} {path} failed with HTTP {exc.code}: {detail}"
            ) from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"GitHub API {method} {path} failed: {exc.reason}") from exc
        return json.loads(body) if body else None

    def _paginated_list(
        self, endpoint: str, key: str | None = None, total_key: str | None = None
    ) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        expected_total: int | None = None
        page = 1
        while True:
            separator = "&" if "?" in endpoint else "?"
            payload = self.request("GET", f"{endpoint}{separator}per_page={PER_PAGE}&page={page}")
            if key and not isinstance(payload, dict):
                raise RuntimeError(f"GitHub API returned an invalid response for {endpoint}")
            if key and key not in payload:
                raise RuntimeError(f"GitHub API response for {endpoint} did not contain {key!r}")
            if total_key and page == 1:
                total = payload.get(total_key) if isinstance(payload, dict) else None
                if type(total) is not int or total < 0:
                    raise RuntimeError(
                        f"GitHub API response for {endpoint} had an invalid {total_key!r}"
                    )
                expected_total = total
            items = payload[key] if key else payload
            if not isinstance(items, list):
                raise RuntimeError(f"GitHub API returned an invalid collection for {endpoint}")
            if not all(isinstance(item, dict) for item in items):
                raise RuntimeError(f"GitHub API returned an invalid item for {endpoint}")
            results.extend(items)
            if len(items) < PER_PAGE:
                if expected_total is not None and len(results) != expected_total:
                    raise RuntimeError(
                        f"GitHub API returned {len(results)} of {expected_total} items for {endpoint}"
                    )
                return results
            page += 1

    def list_releases(self) -> list[dict[str, Any]]:
        return self._paginated_list(f"/repos/{self.repository}/releases")

    def get_latest_release(self) -> dict[str, Any] | None:
        payload = self.request(
            "GET", f"/repos/{self.repository}/releases/latest", allow_not_found=True
        )
        if payload is _NOT_FOUND:
            return None
        if not isinstance(payload, dict):
            raise RuntimeError("GitHub API returned an invalid latest release")
        return payload

    def get_default_branch_head(self) -> tuple[str, str]:
        """Return the repository's validated current default branch and commit SHA."""
        repository = self.request("GET", f"/repos/{self.repository}")
        if not isinstance(repository, dict):
            raise RuntimeError("GitHub API returned an invalid repository response")
        default_branch = _required_string(
            repository.get("default_branch"), "repository default branch"
        )
        encoded_branch = urllib.parse.quote(default_branch, safe="")
        commit = self.request("GET", f"/repos/{self.repository}/commits/{encoded_branch}")
        if not isinstance(commit, dict):
            raise RuntimeError("GitHub API returned an invalid default-branch commit")
        sha = _required_string(commit.get("sha"), "default-branch commit SHA")
        if re.fullmatch(r"[0-9a-f]{40}", sha) is None:
            raise RuntimeError("GitHub API returned an invalid default-branch commit SHA")
        return default_branch, sha

    def list_artifacts(self) -> list[dict[str, Any]]:
        return self._paginated_list(
            f"/repos/{self.repository}/actions/artifacts",
            key="artifacts",
            total_key="total_count",
        )

    def list_deployments(self) -> list[dict[str, Any]]:
        return self._paginated_list(f"/repos/{self.repository}/deployments")

    def get_latest_deployment_status(self, deployment_id: int) -> str | None:
        payload = self.request(
            "GET",
            f"/repos/{self.repository}/deployments/{deployment_id}/statuses?per_page=1&page=1",
            allow_not_found=True,
        )
        if payload is _NOT_FOUND:
            return None
        if not isinstance(payload, list) or not all(isinstance(item, dict) for item in payload):
            raise RuntimeError(
                f"GitHub API returned invalid statuses for deployment {deployment_id}"
            )
        if not payload:
            return None
        state = payload[0].get("state")
        if not isinstance(state, str) or not state:
            raise RuntimeError(
                f"GitHub API returned an invalid status for deployment {deployment_id}"
            )
        return state

    def get_workflow_run(self, run_id: int) -> dict[str, Any] | None:
        payload = self.request(
            "GET",
            f"/repos/{self.repository}/actions/runs/{run_id}",
            allow_not_found=True,
        )
        if payload is _NOT_FOUND:
            return None
        if not isinstance(payload, dict):
            raise RuntimeError(f"GitHub API returned an invalid workflow run {run_id}")
        return payload

    def delete_release_asset(self, asset_id: int) -> bool:
        result = self.request(
            "DELETE",
            f"/repos/{self.repository}/releases/assets/{asset_id}",
            allow_not_found=True,
        )
        return result is not _NOT_FOUND

    def delete_artifact(self, artifact_id: int) -> bool:
        result = self.request(
            "DELETE",
            f"/repos/{self.repository}/actions/artifacts/{artifact_id}",
            allow_not_found=True,
        )
        return result is not _NOT_FOUND


def positive_int(value: object, label: str) -> int:
    if type(value) is not int or value <= 0:
        raise RuntimeError(f"GitHub API returned an invalid {label}")
    return value


def _nonnegative_int(value: object, label: str) -> int:
    if type(value) is not int or value < 0:
        raise RuntimeError(f"GitHub API returned an invalid {label}")
    return value


def _required_string(value: object, label: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str) or (not allow_empty and not value):
        raise RuntimeError(f"GitHub API returned an invalid {label}")
    return value


def _validate_release(release: dict[str, Any], label: str) -> None:
    positive_int(release.get("id"), f"{label} id")
    _required_string(release.get("tag_name"), f"{label} tag")
    if type(release.get("draft")) is not bool or type(release.get("prerelease")) is not bool:
        raise RuntimeError(f"GitHub API returned invalid flags for {label}")
    body = release.get("body")
    if body is not None and not isinstance(body, str):
        raise RuntimeError(f"GitHub API returned an invalid body for {label}")
    assets = release.get("assets")
    if not isinstance(assets, list) or not all(isinstance(asset, dict) for asset in assets):
        raise RuntimeError(f"GitHub API returned invalid assets for {label}")
    for index, asset in enumerate(assets):
        asset_label = f"{label} asset {index}"
        positive_int(asset.get("id"), f"{asset_label} id")
        _required_string(asset.get("name"), f"{asset_label} name")
        _nonnegative_int(asset.get("size"), f"{asset_label} size")
        _required_string(asset.get("browser_download_url"), f"{asset_label} URL")


def _validate_artifact(artifact: dict[str, Any], label: str) -> None:
    positive_int(artifact.get("id"), f"{label} id")
    _required_string(artifact.get("name"), f"{label} name")
    _nonnegative_int(artifact.get("size_in_bytes"), f"{label} size")
    if type(artifact.get("expired")) is not bool:
        raise RuntimeError(f"GitHub API returned an invalid expired flag for {label}")
    _required_string(artifact.get("archive_download_url"), f"{label} URL")
    workflow_run = artifact.get("workflow_run")
    if workflow_run is not None:
        if not isinstance(workflow_run, dict):
            raise RuntimeError(f"GitHub API returned invalid workflow metadata for {label}")
        positive_int(workflow_run.get("id"), f"{label} workflow run id")


def _validate_deployment(deployment: dict[str, Any], label: str) -> None:
    positive_int(deployment.get("id"), f"{label} id")
    _required_string(deployment.get("ref"), f"{label} ref", allow_empty=True)


def _validate_unique_ids(items: Iterable[dict[str, Any]], label: str) -> None:
    ids = [positive_int(item.get("id"), f"{label} id") for item in items]
    if len(ids) != len(set(ids)):
        raise RuntimeError(f"GitHub API returned duplicate {label} ids")


def validate_inventory(
    releases: list[dict[str, Any]],
    artifacts: list[dict[str, Any]],
    deployments: list[dict[str, Any]],
    latest_release: dict[str, Any] | None,
) -> None:
    """Validate the complete cleanup inventory before policy evaluation."""
    for index, release in enumerate(releases):
        _validate_release(release, f"release {index}")
    for index, artifact in enumerate(artifacts):
        _validate_artifact(artifact, f"artifact {index}")
    for index, deployment in enumerate(deployments):
        _validate_deployment(deployment, f"deployment {index}")
    if latest_release is not None:
        _validate_release(latest_release, "latest release")
    _validate_unique_ids(releases, "release")
    _validate_unique_ids(artifacts, "artifact")
    _validate_unique_ids(deployments, "deployment")
    release_assets = [asset for release in releases for asset in release["assets"]]
    _validate_unique_ids(release_assets, "release asset")


def validate_workflow_run(run: dict[str, Any], run_id: int) -> None:
    """Validate producer-run fields used to authorize artifact deletion."""
    for field in ("status", "event", "path"):
        _required_string(run.get(field), f"workflow run {run_id} {field}")
    head_branch = run.get("head_branch")
    if head_branch is not None and not isinstance(head_branch, str):
        raise RuntimeError(f"GitHub API returned invalid workflow run {run_id} head_branch")
