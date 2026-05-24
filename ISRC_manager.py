# ------------------------------------------------------------
# Created by M. van de Kleut
# 22-aug-2025
#
# License:
# This software is provided "as is", without warranty of any kind.
# Free to use, copy, and distribute for any purpose, provided that
# original credits are retained. Not for resale.
# ------------------------------------------------------------

from __future__ import annotations

import sys

from isrc_manager.main_window import main as _main_window_main

__all__ = ["main"]


def main() -> int:
    return _main_window_main()


if __name__ == "__main__":
    sys.exit(main())
