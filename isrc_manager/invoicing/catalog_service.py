"""Billable service catalog for invoice line defaults."""

from __future__ import annotations

import sqlite3

from .models import InvoiceCatalogItemPayload, InvoiceCatalogItemRecord, Quantity
from .money import normalize_currency, normalize_vat_treatment, parse_quantity


def _clean_text(value: object | None) -> str | None:
    text = str(value or "").strip()
    return text or None


class InvoiceCatalogService:
    """Maintains billable catalog services and default costs."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    @staticmethod
    def _payload_quantity(payload: InvoiceCatalogItemPayload) -> Quantity:
        quantity = payload.default_quantity
        return quantity if isinstance(quantity, Quantity) else parse_quantity(quantity)

    def create_item(self, payload: InvoiceCatalogItemPayload) -> int:
        clean_name = _clean_text(payload.name)
        if clean_name is None:
            raise ValueError("Catalog item name is required.")
        quantity = self._payload_quantity(payload)
        if int(payload.default_unit_price_minor) < 0:
            raise ValueError("Default unit price must be non-negative.")
        if int(payload.default_vat_rate_basis_points) < 0:
            raise ValueError("Default VAT rate must be non-negative.")
        with self.conn:
            cur = self.conn.execute(
                """
                INSERT INTO InvoiceCatalogItems(
                    name,
                    description,
                    default_quantity_value,
                    default_quantity_scale,
                    default_unit_price_minor,
                    default_vat_treatment,
                    default_vat_rate_basis_points,
                    vat_country_code,
                    currency,
                    category,
                    default_account_code,
                    active
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    clean_name,
                    _clean_text(payload.description),
                    int(quantity.value),
                    int(quantity.scale),
                    int(payload.default_unit_price_minor),
                    normalize_vat_treatment(payload.default_vat_treatment),
                    int(payload.default_vat_rate_basis_points),
                    _clean_text(payload.vat_country_code),
                    normalize_currency(payload.currency),
                    _clean_text(payload.category),
                    _clean_text(payload.default_account_code),
                    1 if payload.active else 0,
                ),
            )
            return int(cur.lastrowid)

    def update_item(
        self, item_id: int, payload: InvoiceCatalogItemPayload
    ) -> InvoiceCatalogItemRecord:
        clean_name = _clean_text(payload.name)
        if clean_name is None:
            raise ValueError("Catalog item name is required.")
        quantity = self._payload_quantity(payload)
        if int(payload.default_unit_price_minor) < 0:
            raise ValueError("Default unit price must be non-negative.")
        if int(payload.default_vat_rate_basis_points) < 0:
            raise ValueError("Default VAT rate must be non-negative.")
        with self.conn:
            cur = self.conn.execute(
                """
                UPDATE InvoiceCatalogItems
                SET name=?,
                    description=?,
                    default_quantity_value=?,
                    default_quantity_scale=?,
                    default_unit_price_minor=?,
                    default_vat_treatment=?,
                    default_vat_rate_basis_points=?,
                    vat_country_code=?,
                    currency=?,
                    category=?,
                    default_account_code=?,
                    active=?,
                    updated_at=datetime('now')
                WHERE id=?
                """,
                (
                    clean_name,
                    _clean_text(payload.description),
                    int(quantity.value),
                    int(quantity.scale),
                    int(payload.default_unit_price_minor),
                    normalize_vat_treatment(payload.default_vat_treatment),
                    int(payload.default_vat_rate_basis_points),
                    _clean_text(payload.vat_country_code),
                    normalize_currency(payload.currency),
                    _clean_text(payload.category),
                    _clean_text(payload.default_account_code),
                    1 if payload.active else 0,
                    int(item_id),
                ),
            )
            if cur.rowcount != 1:
                raise ValueError(f"Invoice catalog item {int(item_id)} was not found.")
        record = self.fetch_item(item_id)
        if record is None:
            raise RuntimeError("Invoice catalog item could not be reloaded.")
        return record

    def list_items(self, *, active_only: bool = False) -> list[InvoiceCatalogItemRecord]:
        where_sql = "WHERE active=1" if active_only else ""
        rows = self.conn.execute(f"""
            SELECT
                id,
                name,
                description,
                default_quantity_value,
                default_quantity_scale,
                default_unit_price_minor,
                default_vat_treatment,
                default_vat_rate_basis_points,
                vat_country_code,
                currency,
                category,
                default_account_code,
                active,
                created_at,
                updated_at
            FROM InvoiceCatalogItems
            {where_sql}
            ORDER BY active DESC, COALESCE(category, ''), name, id
            """).fetchall()
        return [self._row_to_record(row) for row in rows]

    def fetch_item(self, item_id: int) -> InvoiceCatalogItemRecord | None:
        row = self.conn.execute(
            """
            SELECT
                id,
                name,
                description,
                default_quantity_value,
                default_quantity_scale,
                default_unit_price_minor,
                default_vat_treatment,
                default_vat_rate_basis_points,
                vat_country_code,
                currency,
                category,
                default_account_code,
                active,
                created_at,
                updated_at
            FROM InvoiceCatalogItems
            WHERE id=?
            """,
            (int(item_id),),
        ).fetchone()
        if not row:
            return None
        return self._row_to_record(row)

    @staticmethod
    def _row_to_record(row) -> InvoiceCatalogItemRecord:
        return InvoiceCatalogItemRecord(
            id=int(row[0]),
            name=str(row[1] or ""),
            description=_clean_text(row[2]),
            default_quantity_value=int(row[3] or 1),
            default_quantity_scale=int(row[4] or 0),
            default_unit_price_minor=int(row[5] or 0),
            default_vat_treatment=str(row[6] or ""),
            default_vat_rate_basis_points=int(row[7] or 0),
            vat_country_code=_clean_text(row[8]),
            currency=str(row[9] or ""),
            category=_clean_text(row[10]),
            default_account_code=_clean_text(row[11]),
            active=bool(row[12]),
            created_at=_clean_text(row[13]),
            updated_at=_clean_text(row[14]),
        )
