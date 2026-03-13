"""Shared application constants."""

APP_ORG = "GenericVendor"
APP_NAME = "ISRCManager"
SETTINGS_BASENAME = "settings.ini"

QSETTINGS_ORG = APP_ORG
QSETTINGS_APP = APP_NAME

DEFAULT_WINDOW_TITLE = "ISRC Manager"
DEFAULT_ICON_PATH = ""

FIELD_TYPE_CHOICES = ["text", "dropdown", "checkbox", "date", "blob_image", "blob_audio"]

SCHEMA_BASELINE = 1
SCHEMA_TARGET = 13

DEFAULT_BASE_HEADERS = [
    "ID",
    "Audio File",
    "Track Title",
    "Track Length (hh:mm:ss)",
    "Album Title",
    "Album Art",
    "Artist Name",
    "Additional Artists",
    "ISRC",
    "BUMA Wnr.",
    "ISWC",
    "UPC",
    "Catalog#",
    "Entry Date",
    "Release Date",
    "Genre",
]

PROMOTED_CUSTOM_FIELDS = (
    {
        "name": "Audio File",
        "field_type": "blob_audio",
        "path_column": "audio_file_path",
        "mime_column": "audio_file_mime_type",
        "size_column": "audio_file_size_bytes",
    },
    {
        "name": "Album Art",
        "field_type": "blob_image",
        "path_column": "album_art_path",
        "mime_column": "album_art_mime_type",
        "size_column": "album_art_size_bytes",
    },
    {
        "name": "BUMA Wnr.",
        "field_type": "text",
        "value_column": "buma_work_number",
    },
    {
        "name": "Catalog#",
        "field_type": "text",
        "value_column": "catalog_number",
    },
)

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
