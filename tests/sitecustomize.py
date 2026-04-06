"""Test-directory startup bootstrap for direct script execution."""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

try:
    from isrc_manager.external_launch import (
        install_test_process_desktop_safety_if_needed,
        install_unittest_test_process_desktop_safety_hook,
    )
except Exception:  # pragma: no cover - startup safety fallback
    install_test_process_desktop_safety_if_needed = None
    install_unittest_test_process_desktop_safety_hook = None


if callable(install_test_process_desktop_safety_if_needed):  # pragma: no branch
    try:
        install_test_process_desktop_safety_if_needed()
    except Exception:
        pass

if callable(install_unittest_test_process_desktop_safety_hook):  # pragma: no branch
    try:
        install_unittest_test_process_desktop_safety_hook()
    except Exception:
        pass
