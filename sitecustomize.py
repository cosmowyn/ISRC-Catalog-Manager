"""Automatic test-process desktop-safety bootstrap."""

from __future__ import annotations

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
