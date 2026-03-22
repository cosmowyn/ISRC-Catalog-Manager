"""Audio metadata tag models and services."""

from .mapping import (
    TagConflictPreview,
    TagImportPatch,
    catalog_metadata_to_tags,
    merge_imported_tags,
)
from .models import (
    ArtworkPayload,
    AudioTagData,
    BulkAudioAttachPlan,
    BulkAudioAttachPlanItem,
    BulkAudioAttachResult,
    BulkAudioAttachTrackCandidate,
    TagFieldConflict,
    TaggedAudioExportResult,
)
from .service import AudioTagService, BulkAudioAttachService, TaggedAudioExportService

__all__ = [
    "ArtworkPayload",
    "AudioTagData",
    "AudioTagService",
    "BulkAudioAttachPlan",
    "BulkAudioAttachPlanItem",
    "BulkAudioAttachResult",
    "BulkAudioAttachService",
    "BulkAudioAttachTrackCandidate",
    "catalog_metadata_to_tags",
    "TagConflictPreview",
    "TagFieldConflict",
    "TagImportPatch",
    "TaggedAudioExportResult",
    "TaggedAudioExportService",
    "merge_imported_tags",
]
