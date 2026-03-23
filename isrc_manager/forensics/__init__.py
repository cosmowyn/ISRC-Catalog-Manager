"""Recipient-specific forensic watermark export helpers."""

from .models import (
    AUTHENTICITY_BASIS_FORENSIC_TRACE,
    DERIVATIVE_KIND_FORENSIC_WATERMARKED_COPY,
    FORENSIC_STATUS_MATCH_FOUND,
    FORENSIC_STATUS_MATCH_LOW_CONFIDENCE,
    FORENSIC_STATUS_NOT_DETECTED,
    FORENSIC_STATUS_TOKEN_UNRESOLVED,
    FORENSIC_STATUS_UNSUPPORTED_OR_INSUFFICIENT,
    FORENSIC_TOKEN_VERSION,
    FORENSIC_WATERMARK_VERSION,
    WORKFLOW_KIND_FORENSIC_EXPORT,
    ForensicExportRecord,
    ForensicExportRequest,
    ForensicExportResult,
    ForensicInspectionReport,
    ForensicWatermarkExtractionResult,
    ForensicWatermarkToken,
)
from .service import (
    ForensicExportCoordinator,
    ForensicLedgerService,
    ForensicWatermarkService,
)
from .watermark import (
    ForensicWatermarkCore,
    forensic_watermark_settings_payload,
    supported_forensic_audio_path,
)

try:  # pragma: no cover - Qt dialog imports are optional in headless service tests
    from .dialogs import ForensicExportDialog, ForensicInspectionDialog
except Exception:  # pragma: no cover
    ForensicExportDialog = None
    ForensicInspectionDialog = None

__all__ = [
    "AUTHENTICITY_BASIS_FORENSIC_TRACE",
    "DERIVATIVE_KIND_FORENSIC_WATERMARKED_COPY",
    "FORENSIC_STATUS_MATCH_FOUND",
    "FORENSIC_STATUS_MATCH_LOW_CONFIDENCE",
    "FORENSIC_STATUS_NOT_DETECTED",
    "FORENSIC_STATUS_TOKEN_UNRESOLVED",
    "FORENSIC_STATUS_UNSUPPORTED_OR_INSUFFICIENT",
    "FORENSIC_TOKEN_VERSION",
    "FORENSIC_WATERMARK_VERSION",
    "ForensicExportCoordinator",
    "ForensicExportDialog",
    "ForensicExportRecord",
    "ForensicExportRequest",
    "ForensicExportResult",
    "ForensicInspectionDialog",
    "ForensicInspectionReport",
    "ForensicLedgerService",
    "ForensicWatermarkCore",
    "ForensicWatermarkExtractionResult",
    "ForensicWatermarkService",
    "ForensicWatermarkToken",
    "WORKFLOW_KIND_FORENSIC_EXPORT",
    "forensic_watermark_settings_payload",
    "supported_forensic_audio_path",
]
