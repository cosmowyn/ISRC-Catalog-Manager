"""Fixed OS credential namespaces owned by the application."""

from __future__ import annotations

DATABASE_CREDENTIAL_SERVICE = "isrc-catalog-manager.database"
SOUNDCLOUD_CREDENTIAL_SERVICE = "isrc-catalog-manager.soundcloud"

APP_CREDENTIAL_SERVICES = (
    DATABASE_CREDENTIAL_SERVICE,
    SOUNDCLOUD_CREDENTIAL_SERVICE,
)

__all__ = [
    "APP_CREDENTIAL_SERVICES",
    "DATABASE_CREDENTIAL_SERVICE",
    "SOUNDCLOUD_CREDENTIAL_SERVICE",
]
