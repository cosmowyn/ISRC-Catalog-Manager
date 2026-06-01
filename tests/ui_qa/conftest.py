from __future__ import annotations

import pytest

from isrc_manager.qa import UIQualificationHarness


@pytest.fixture(scope="session")
def ui_pq_harness():
    with UIQualificationHarness() as harness:
        harness.run_full_qualification()
        yield harness
