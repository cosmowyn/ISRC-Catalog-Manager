"""Runtime application version helpers.

``pyproject.toml`` is the canonical version source. ``__version__`` is kept in
sync by release automation so source checkouts and frozen builds still have a
safe fallback when package metadata is unavailable.
"""

from __future__ import annotations

from importlib import metadata

PACKAGE_NAME = "isrc-catalog-manager"
__version__ = "3.6.17"


def current_app_version(package_names: tuple[str, ...] | None = None) -> str:
    candidates = package_names or (PACKAGE_NAME,)
    for package_name in candidates:
        try:
            return metadata.version(package_name)
        except metadata.PackageNotFoundError:
            continue
        except Exception:
            break
    return __version__
