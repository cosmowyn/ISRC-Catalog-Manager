"""Shared application constants."""

from isrc_manager.domain.standard_fields import default_base_headers, promoted_custom_fields

APP_ORG = "GenericVendor"
APP_NAME = "ISRCManager"
SETTINGS_BASENAME = "settings.ini"

QSETTINGS_ORG = APP_ORG
QSETTINGS_APP = APP_NAME

DEFAULT_WINDOW_TITLE = "ISRC Manager"
DEFAULT_ICON_PATH = ""
DEFAULT_AUTO_SNAPSHOT_ENABLED = True
DEFAULT_AUTO_SNAPSHOT_INTERVAL_MINUTES = 30
MIN_AUTO_SNAPSHOT_INTERVAL_MINUTES = 5
MAX_AUTO_SNAPSHOT_INTERVAL_MINUTES = 1440

FIELD_TYPE_CHOICES = ["text", "dropdown", "checkbox", "date", "blob_image", "blob_audio"]

SCHEMA_BASELINE = 1
SCHEMA_TARGET = 25

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
