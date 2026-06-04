"""Recipient-specific forensic watermark export helpers."""

from __future__ import annotations

from importlib import import_module

from .models import (
    AUTHENTICITY_BASIS_FORENSIC_TRACE,
    DERIVATIVE_KIND_FORENSIC_WATERMARKED_COPY,
    FORENSIC_STATUS_MATCH_FOUND,
    FORENSIC_STATUS_MATCH_LIKELY,
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

_LAZY_EXPORTS = {
    "ForensicExportCoordinator": ".service",
    "ForensicLedgerService": ".service",
    "ForensicWatermarkService": ".service",
    "ForensicWatermarkCore": ".watermark",
    "forensic_watermark_settings_payload": ".watermark",
    "supported_forensic_audio_path": ".watermark",
}

_OPTIONAL_DIALOG_EXPORTS = {
    "ForensicExportDialog": ".dialogs",
    "ForensicInspectionDialog": ".dialogs",
}


def __getattr__(name: str):
    module_name = _LAZY_EXPORTS.get(name)
    if module_name is not None:
        value = getattr(import_module(module_name, __name__), name)
        globals()[name] = value
        return value
    module_name = _OPTIONAL_DIALOG_EXPORTS.get(name)
    if module_name is not None:
        try:
            value = getattr(import_module(module_name, __name__), name)
        except Exception:
            value = None
        globals()[name] = value
        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "AUTHENTICITY_BASIS_FORENSIC_TRACE",
    "DERIVATIVE_KIND_FORENSIC_WATERMARKED_COPY",
    "FORENSIC_STATUS_MATCH_FOUND",
    "FORENSIC_STATUS_MATCH_LIKELY",
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
