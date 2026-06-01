"""Runtime configuration for crash and bug report submission."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from isrc_manager.paths import RES_DIR

DEFAULT_REPOSITORY = "cosmowyn/ISRC-Catalog-Manager"
ENV_REPORT_PROXY_URL = "ISRC_REPORT_PROXY_URL"
ENV_REPORT_REPOSITORY = "ISRC_REPORT_REPOSITORY"
BUNDLED_REPORTING_CONFIG = Path("resources") / "reporting.json"


@dataclass(frozen=True, slots=True)
class ReportingConfiguration:
    repository: str = DEFAULT_REPOSITORY
    proxy_url: str = ""
    source: str = "defaults"


def load_reporting_configuration(
    *,
    environ: Mapping[str, str] | None = None,
    resource_root: Path | None = None,
) -> ReportingConfiguration:
    """Load public reporting config from environment first, then bundled resources.

    The desktop app may contain a public HTTPS report-proxy URL, but never a GitHub token,
    private key, password, or shared account credential.
    """

    env = os.environ if environ is None else environ
    env_repository = _clean_text(env.get(ENV_REPORT_REPOSITORY, ""))
    env_has_proxy = ENV_REPORT_PROXY_URL in env
    env_proxy_url = _clean_text(env.get(ENV_REPORT_PROXY_URL, ""))
    bundled = _load_bundled_configuration(resource_root)
    repository = env_repository or bundled.repository or DEFAULT_REPOSITORY
    if env_has_proxy:
        return ReportingConfiguration(
            repository=repository,
            proxy_url=env_proxy_url,
            source="environment",
        )
    if bundled.proxy_url:
        return ReportingConfiguration(
            repository=repository,
            proxy_url=bundled.proxy_url,
            source=bundled.source,
        )
    return ReportingConfiguration(repository=repository)


def _load_bundled_configuration(resource_root: Path | None = None) -> ReportingConfiguration:
    root = Path(resource_root) if resource_root is not None else RES_DIR()
    path = root / BUNDLED_REPORTING_CONFIG
    if not path.is_file():
        return ReportingConfiguration(source="bundled-missing")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return ReportingConfiguration(source="bundled-invalid")
    if not isinstance(payload, dict):
        return ReportingConfiguration(source="bundled-invalid")
    return ReportingConfiguration(
        repository=_clean_text(payload.get("repository", "")) or DEFAULT_REPOSITORY,
        proxy_url=_clean_text(payload.get("proxy_url", "")),
        source=f"bundled:{BUNDLED_REPORTING_CONFIG.as_posix()}",
    )


def _clean_text(value: Any) -> str:
    return str(value or "").strip()
