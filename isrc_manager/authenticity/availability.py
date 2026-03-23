"""Optional dependency helpers for the audio authenticity feature."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from importlib import import_module

OPTIONAL_AUTHENTICITY_MODULES = (
    "cryptography",
    "numpy",
    "scipy",
    "soundfile",
)


@dataclass(frozen=True)
class AuthenticityDependencyStatus:
    available: bool
    missing_modules: tuple[str, ...]


@lru_cache(maxsize=1)
def authenticity_dependency_status() -> AuthenticityDependencyStatus:
    missing_modules: list[str] = []
    for module_name in OPTIONAL_AUTHENTICITY_MODULES:
        try:
            import_module(module_name)
        except Exception:
            missing_modules.append(module_name)
    missing = tuple(missing_modules)
    return AuthenticityDependencyStatus(
        available=(len(missing) == 0),
        missing_modules=missing,
    )


def authenticity_unavailable_message() -> str:
    status = authenticity_dependency_status()
    if status.available:
        return ""
    missing = ", ".join(f"'{name}'" for name in status.missing_modules)
    return (
        "Audio authenticity is unavailable because optional packages are missing: "
        f"{missing}. Install the app dependencies from requirements.txt, or add those "
        "packages to the active Python environment."
    )
