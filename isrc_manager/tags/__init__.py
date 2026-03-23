"""Audio metadata tag models and services."""

from .catalog import build_catalog_tag_data
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
    TaggedAudioExportItem,
    TaggedAudioExportPlanItem,
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
    "build_catalog_tag_data",
    "catalog_metadata_to_tags",
    "TagConflictPreview",
    "TagFieldConflict",
    "TagImportPatch",
    "TaggedAudioExportItem",
    "TaggedAudioExportPlanItem",
    "TaggedAudioExportResult",
    "TaggedAudioExportService",
    "merge_imported_tags",
]
