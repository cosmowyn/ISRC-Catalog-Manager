"""Audio metadata tag models and services."""

from .mapping import (
    TagConflictPreview,
    TagImportPatch,
    catalog_metadata_to_tags,
    merge_imported_tags,
)
from .models import ArtworkPayload, AudioTagData, TagFieldConflict, TaggedAudioExportResult
from .service import AudioTagService, TaggedAudioExportService

__all__ = [
    "ArtworkPayload",
    "AudioTagData",
    "AudioTagService",
    "catalog_metadata_to_tags",
    "TagConflictPreview",
    "TagFieldConflict",
    "TagImportPatch",
    "TaggedAudioExportResult",
    "TaggedAudioExportService",
    "merge_imported_tags",
]
