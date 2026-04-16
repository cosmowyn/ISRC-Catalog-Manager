"""Shared application constants."""

from isrc_manager.domain.standard_fields import default_base_headers, promoted_custom_fields

APP_ORG = "GenericVendor"
APP_NAME = "ISRCManager"
SETTINGS_BASENAME = "settings.ini"

QSETTINGS_ORG = APP_ORG
QSETTINGS_APP = APP_NAME

DEFAULT_WINDOW_TITLE = "ISRC Catalog Manager"
DEFAULT_ICON_PATH = ""
DEFAULT_AUTO_SNAPSHOT_ENABLED = True
DEFAULT_AUTO_SNAPSHOT_INTERVAL_MINUTES = 30
MIN_AUTO_SNAPSHOT_INTERVAL_MINUTES = 5
MAX_AUTO_SNAPSHOT_INTERVAL_MINUTES = 1440
DEFAULT_HISTORY_AUTO_CLEANUP_ENABLED = True
DEFAULT_HISTORY_STORAGE_BUDGET_MB = 2048
MIN_HISTORY_STORAGE_BUDGET_MB = 128
MAX_HISTORY_STORAGE_BUDGET_MB = 1048576
DEFAULT_HISTORY_RETENTION_MODE = "balanced"
HISTORY_RETENTION_MODE_MAXIMUM_SAFETY = "maximum_safety"
HISTORY_RETENTION_MODE_BALANCED = "balanced"
HISTORY_RETENTION_MODE_LEAN = "lean"
HISTORY_RETENTION_MODE_CUSTOM = "custom"
HISTORY_RETENTION_MODE_CHOICES = (
    HISTORY_RETENTION_MODE_MAXIMUM_SAFETY,
    HISTORY_RETENTION_MODE_BALANCED,
    HISTORY_RETENTION_MODE_LEAN,
    HISTORY_RETENTION_MODE_CUSTOM,
)
DEFAULT_HISTORY_AUTO_SNAPSHOT_KEEP_LATEST = 25
MIN_HISTORY_AUTO_SNAPSHOT_KEEP_LATEST = 1
MAX_HISTORY_AUTO_SNAPSHOT_KEEP_LATEST = 10000
DEFAULT_HISTORY_PRUNE_PRE_RESTORE_COPIES_AFTER_DAYS = 0
MIN_HISTORY_PRUNE_PRE_RESTORE_COPIES_AFTER_DAYS = 0
MAX_HISTORY_PRUNE_PRE_RESTORE_COPIES_AFTER_DAYS = 3650
HISTORY_RETENTION_MODE_PRESETS = {
    HISTORY_RETENTION_MODE_MAXIMUM_SAFETY: {
        "auto_cleanup_enabled": True,
        "storage_budget_mb": 4096,
        "auto_snapshot_keep_latest": 50,
        "prune_pre_restore_copies_after_days": 0,
    },
    HISTORY_RETENTION_MODE_BALANCED: {
        "auto_cleanup_enabled": True,
        "storage_budget_mb": DEFAULT_HISTORY_STORAGE_BUDGET_MB,
        "auto_snapshot_keep_latest": DEFAULT_HISTORY_AUTO_SNAPSHOT_KEEP_LATEST,
        "prune_pre_restore_copies_after_days": DEFAULT_HISTORY_PRUNE_PRE_RESTORE_COPIES_AFTER_DAYS,
    },
    HISTORY_RETENTION_MODE_LEAN: {
        "auto_cleanup_enabled": True,
        "storage_budget_mb": 1024,
        "auto_snapshot_keep_latest": 10,
        "prune_pre_restore_copies_after_days": 7,
    },
}

FIELD_TYPE_CHOICES = ["text", "dropdown", "checkbox", "date", "blob_image", "blob_audio"]

SCHEMA_BASELINE = 1
SCHEMA_TARGET = 40

DEFAULT_BASE_HEADERS = default_base_headers()

PROMOTED_CUSTOM_FIELDS = promoted_custom_fields()

PROMOTED_CUSTOM_FIELD_NAMES = {field["name"] for field in PROMOTED_CUSTOM_FIELDS}

DEFAULT_HIDDEN_CUSTOM_COLUMN_NAMES = {
    "Distribution Status",
    "Mastered",
    "Lyrics",
    "Notes",
    "Buy URL",
}

CUSTOM_KIND_TEXT = "text"
CUSTOM_KIND_INT = "int"
CUSTOM_KIND_DATE = "date"
CUSTOM_KIND_BLOB_IMAGE = "blob_image"
CUSTOM_KIND_BLOB_AUDIO = "blob_audio"

ALLOWED_CUSTOM_KINDS = [
    CUSTOM_KIND_TEXT,
    CUSTOM_KIND_INT,
    CUSTOM_KIND_DATE,
    CUSTOM_KIND_BLOB_IMAGE,
    CUSTOM_KIND_BLOB_AUDIO,
]

BLOB_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tif", ".tiff"}
BLOB_AUDIO_EXTS = {".wav", ".aif", ".aiff", ".mp3", ".flac", ".m4a", ".aac", ".ogg", ".opus"}
MAX_BLOB_BYTES = 256 * 1024 * 1024
