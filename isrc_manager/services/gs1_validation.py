"""Validation rules for canonical GS1 metadata."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from .gs1_mapping import field_label
from .gs1_models import GS1MetadataRecord, GS1ValidationIssue, GS1ValidationResult, REQUIRED_GS1_METADATA_FIELDS


class GS1ValidationService:
    """Applies storage and export validation rules to GS1 metadata."""

    MAX_PRODUCT_DESCRIPTION_LENGTH = 300
    MAX_IMAGE_URL_LENGTH = 500
    MAX_BRAND_LENGTH = 70
    MAX_SUBBRAND_LENGTH = 70

    def validate(self, record: GS1MetadataRecord, *, for_export: bool = False) -> GS1ValidationResult:
        issues: list[GS1ValidationIssue] = []

        for field_name in REQUIRED_GS1_METADATA_FIELDS:
            value = getattr(record, field_name)
            if str(value or "").strip() == "":
                issues.append(
                    GS1ValidationIssue(
                        field_name=field_name,
                        message=f"{field_label(field_name)} is required.",
                    )
                )

        description = record.product_description.strip()
        if description and len(description) > self.MAX_PRODUCT_DESCRIPTION_LENGTH:
            issues.append(
                GS1ValidationIssue(
                    field_name="product_description",
                    message=(
                        f"Product Description must be {self.MAX_PRODUCT_DESCRIPTION_LENGTH} characters "
                        f"or fewer."
                    ),
                )
            )

        brand = record.brand.strip()
        if brand and len(brand) > self.MAX_BRAND_LENGTH:
            issues.append(
                GS1ValidationIssue(
                    field_name="brand",
                    message=f"Brand must be {self.MAX_BRAND_LENGTH} characters or fewer.",
                )
            )

        subbrand = record.subbrand.strip()
        if subbrand and len(subbrand) > self.MAX_SUBBRAND_LENGTH:
            issues.append(
                GS1ValidationIssue(
                    field_name="subbrand",
                    message=f"Subbrand must be {self.MAX_SUBBRAND_LENGTH} characters or fewer.",
                )
            )

        image_url = record.image_url.strip()
        if image_url and len(image_url) > self.MAX_IMAGE_URL_LENGTH:
            issues.append(
                GS1ValidationIssue(
                    field_name="image_url",
                    message=f"Image URL must be {self.MAX_IMAGE_URL_LENGTH} characters or fewer.",
                )
            )

        quantity = record.quantity.strip()
        if quantity:
            try:
                decimal_quantity = Decimal(quantity)
                if decimal_quantity <= 0:
                    raise InvalidOperation()
            except (InvalidOperation, ValueError):
                issues.append(
                    GS1ValidationIssue(
                        field_name="quantity",
                        message="Quantity must be a positive numeric value.",
                    )
                )

        if for_export and not bool(record.export_enabled):
            issues.append(
                GS1ValidationIssue(
                    field_name="export_enabled",
                    message="Export is disabled for this record.",
                )
            )

        return GS1ValidationResult(issues=issues)

