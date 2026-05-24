"""Shared contract template exceptions."""

from __future__ import annotations


class ContractTemplateIngestionError(RuntimeError):
    """Raised when a template source cannot be converted or scanned."""
