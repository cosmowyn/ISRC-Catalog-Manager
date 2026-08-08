from __future__ import annotations

import json
import os
from collections.abc import Mapping
from pathlib import Path

import pytest

from isrc_manager.qa import UIQualificationHarness


def _ui_pq_configuration_from_env(
    environ: Mapping[str, str],
) -> tuple[Path, tuple[str, ...] | None]:
    artifact_dir = Path(environ.get("ISRC_UI_PQ_ARTIFACT_DIR", "artifacts/ui_pq"))
    raw_components = environ.get("ISRC_UI_PQ_COMPONENTS")
    if raw_components is None:
        return artifact_dir, None
    try:
        parsed = json.loads(raw_components)
    except json.JSONDecodeError as exc:
        raise pytest.UsageError("ISRC_UI_PQ_COMPONENTS must be a JSON array of strings.") from exc
    if not isinstance(parsed, list) or not all(isinstance(value, str) for value in parsed):
        raise pytest.UsageError("ISRC_UI_PQ_COMPONENTS must be a JSON array of strings.")
    return artifact_dir, tuple(parsed)


@pytest.fixture(scope="session")
def ui_pq_harness():
    artifact_dir, components = _ui_pq_configuration_from_env(os.environ)
    with UIQualificationHarness(artifact_dir) as harness:
        harness.run_qualification(components)
        yield harness
