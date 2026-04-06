"""Suite-wide test bootstrap."""

from __future__ import annotations

import os

os.environ.setdefault("ISRC_MANAGER_BLOCK_EXTERNAL_LAUNCHES", "1")

from isrc_manager.external_launch import install_test_external_launch_guard

install_test_external_launch_guard()
