"""Audio watermarking and signed authenticity services."""

from .availability import (
    OPTIONAL_AUTHENTICITY_MODULES,
    authenticity_dependency_status,
    authenticity_unavailable_message,
)
from .models import (
    AUTHENTICITY_SCHEMA_VERSION,
    DIRECT_WATERMARK_SUFFIXES,
    DOCUMENT_TYPE_DIRECT_WATERMARK,
    DOCUMENT_TYPE_PROVENANCE_LINEAGE,
    PROVENANCE_ONLY_SUFFIXES,
    SUPPORTED_AUTHENTICITY_SUFFIXES,
    VERIFICATION_INPUT_SUFFIXES,
    VERIFICATION_STATUS_MANIFEST_REFERENCE_MISMATCH,
    VERIFICATION_STATUS_NO_WATERMARK,
    VERIFICATION_STATUS_SIGNATURE_INVALID,
    VERIFICATION_STATUS_UNSUPPORTED_OR_INSUFFICIENT,
    VERIFICATION_STATUS_VERIFIED,
    VERIFICATION_STATUS_VERIFIED_BY_LINEAGE,
    WATERMARK_VERSION,
    WORKFLOW_KIND_AUTHENTICITY_LINEAGE,
    WORKFLOW_KIND_AUTHENTICITY_MASTER,
    AuthenticityExportPlan,
    AuthenticityExportPlanItem,
    AuthenticityExportResult,
    AuthenticityKeyRecord,
    AuthenticityManifestRecord,
    AuthenticityVerificationReport,
    PreparedAuthenticityManifest,
    ReferenceAudioSelection,
    WatermarkExtractionResult,
    WatermarkToken,
)

try:
    from .service import (
        AudioAuthenticityService,
        AudioWatermarkService,
        AuthenticityKeyService,
        AuthenticityManifestService,
    )
except ModuleNotFoundError as exc:  # pragma: no cover - optional dependency fallback
    if exc.name not in OPTIONAL_AUTHENTICITY_MODULES:
        raise
    AudioAuthenticityService = None
    AudioWatermarkService = None
    AuthenticityKeyService = None
    AuthenticityManifestService = None
    _AUTHENTICITY_IMPORT_ERROR = exc
else:
    _AUTHENTICITY_IMPORT_ERROR = None

_AUTHENTICITY_DEPENDENCY_STATUS = authenticity_dependency_status()
if not _AUTHENTICITY_DEPENDENCY_STATUS.available:
    AudioAuthenticityService = None
    AudioWatermarkService = None
    AuthenticityKeyService = None
    AuthenticityManifestService = None
AUTHENTICITY_FEATURE_AVAILABLE = (
    _AUTHENTICITY_DEPENDENCY_STATUS.available
    and _AUTHENTICITY_IMPORT_ERROR is None
    and AudioAuthenticityService is not None
    and AudioWatermarkService is not None
    and AuthenticityKeyService is not None
    and AuthenticityManifestService is not None
)

try:  # pragma: no cover - optional Qt import for headless service tests
    if AUTHENTICITY_FEATURE_AVAILABLE:
        from .dialogs import (
            AuthenticityExportPreviewDialog,
            AuthenticityKeysDialog,
            AuthenticityVerificationDialog,
        )
    else:
        raise ImportError("Audio authenticity services are unavailable.")
except Exception:  # pragma: no cover - dialog imports are optional outside the desktop app
    AuthenticityExportPreviewDialog = None
    AuthenticityKeysDialog = None
    AuthenticityVerificationDialog = None

__all__ = [
    "AUTHENTICITY_SCHEMA_VERSION",
    "AUTHENTICITY_FEATURE_AVAILABLE",
    "DIRECT_WATERMARK_SUFFIXES",
    "DOCUMENT_TYPE_DIRECT_WATERMARK",
    "DOCUMENT_TYPE_PROVENANCE_LINEAGE",
    "PROVENANCE_ONLY_SUFFIXES",
    "SUPPORTED_AUTHENTICITY_SUFFIXES",
    "VERIFICATION_INPUT_SUFFIXES",
    "VERIFICATION_STATUS_MANIFEST_REFERENCE_MISMATCH",
    "VERIFICATION_STATUS_NO_WATERMARK",
    "VERIFICATION_STATUS_SIGNATURE_INVALID",
    "VERIFICATION_STATUS_UNSUPPORTED_OR_INSUFFICIENT",
    "VERIFICATION_STATUS_VERIFIED",
    "VERIFICATION_STATUS_VERIFIED_BY_LINEAGE",
    "WATERMARK_VERSION",
    "WORKFLOW_KIND_AUTHENTICITY_LINEAGE",
    "WORKFLOW_KIND_AUTHENTICITY_MASTER",
    "AuthenticityExportPlan",
    "AuthenticityExportPlanItem",
    "AuthenticityExportPreviewDialog",
    "AuthenticityExportResult",
    "AuthenticityKeyRecord",
    "AuthenticityKeysDialog",
    "AuthenticityManifestRecord",
    "AuthenticityVerificationDialog",
    "AuthenticityVerificationReport",
    "AudioAuthenticityService",
    "AudioWatermarkService",
    "AuthenticityKeyService",
    "AuthenticityManifestService",
    "authenticity_dependency_status",
    "authenticity_unavailable_message",
    "PreparedAuthenticityManifest",
    "ReferenceAudioSelection",
    "WatermarkExtractionResult",
    "WatermarkToken",
]
