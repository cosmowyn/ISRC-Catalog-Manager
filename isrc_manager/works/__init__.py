"""First-class musical work package."""

from .models import (
    WORK_CREATOR_ROLE_CHOICES,
    WORK_STATUS_CHOICES,
    WorkContributorPayload,
    WorkContributorRecord,
    WorkDetail,
    WorkPayload,
    WorkRecord,
    WorkValidationIssue,
)
from .service import WorkService

__all__ = [
    "WORK_CREATOR_ROLE_CHOICES",
    "WORK_STATUS_CHOICES",
    "WorkContributorPayload",
    "WorkContributorRecord",
    "WorkDetail",
    "WorkPayload",
    "WorkRecord",
    "WorkService",
    "WorkValidationIssue",
]
