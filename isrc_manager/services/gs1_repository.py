"""SQLite persistence for per-track GS1 metadata."""

from __future__ import annotations

import sqlite3

from .gs1_models import GS1MetadataRecord


class GS1MetadataRepository:
    """Reads and writes GS1 metadata linked to the existing track catalog rows."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def fetch_by_track_id(self, track_id: int) -> GS1MetadataRecord | None:
        row = self.conn.execute(
            """
            SELECT
                id,
                track_id,
                status,
                product_classification,
                consumer_unit_flag,
                packaging_type,
                target_market,
                language,
                product_description,
                brand,
                subbrand,
                quantity,
                unit,
                image_url,
                notes,
                export_enabled,
                created_at,
                updated_at
            FROM GS1Metadata
            WHERE track_id = ?
            """,
            (int(track_id),),
        ).fetchone()
        if row is None:
            return None
        return GS1MetadataRecord(
            id=int(row[0]),
            track_id=int(row[1]),
            status=str(row[2] or "").strip(),
            product_classification=str(row[3] or "").strip(),
            consumer_unit_flag=bool(int(row[4] or 0)),
            packaging_type=str(row[5] or "").strip(),
            target_market=str(row[6] or "").strip(),
            language=str(row[7] or "").strip(),
            product_description=str(row[8] or "").strip(),
            brand=str(row[9] or "").strip(),
            subbrand=str(row[10] or "").strip(),
            quantity=str(row[11] or "").strip(),
            unit=str(row[12] or "").strip(),
            image_url=str(row[13] or "").strip(),
            notes=str(row[14] or "").strip(),
            export_enabled=bool(int(row[15] or 0)),
            created_at=str(row[16] or "").strip() or None,
            updated_at=str(row[17] or "").strip() or None,
        )

    def list_by_track_ids(self, track_ids: list[int]) -> dict[int, GS1MetadataRecord]:
        if not track_ids:
            return {}
        placeholders = ",".join("?" for _ in track_ids)
        rows = self.conn.execute(
            f"""
            SELECT track_id
            FROM GS1Metadata
            WHERE track_id IN ({placeholders})
            """,
            [int(track_id) for track_id in track_ids],
        ).fetchall()
        return {
            int(track_id): record
            for (track_id,) in rows
            if (record := self.fetch_by_track_id(int(track_id))) is not None
        }

    def save(self, record: GS1MetadataRecord) -> GS1MetadataRecord:
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO GS1Metadata (
                    track_id,
                    status,
                    product_classification,
                    consumer_unit_flag,
                    packaging_type,
                    target_market,
                    language,
                    product_description,
                    brand,
                    subbrand,
                    quantity,
                    unit,
                    image_url,
                    notes,
                    export_enabled,
                    created_at,
                    updated_at
                )
                VALUES (
                    ?,
                    ?,
                    ?,
                    ?,
                    ?,
                    ?,
                    ?,
                    ?,
                    ?,
                    ?,
                    ?,
                    ?,
                    ?,
                    ?,
                    ?,
                    COALESCE((SELECT created_at FROM GS1Metadata WHERE track_id = ?), datetime('now')),
                    datetime('now')
                )
                ON CONFLICT(track_id) DO UPDATE SET
                    status=excluded.status,
                    product_classification=excluded.product_classification,
                    consumer_unit_flag=excluded.consumer_unit_flag,
                    packaging_type=excluded.packaging_type,
                    target_market=excluded.target_market,
                    language=excluded.language,
                    product_description=excluded.product_description,
                    brand=excluded.brand,
                    subbrand=excluded.subbrand,
                    quantity=excluded.quantity,
                    unit=excluded.unit,
                    image_url=excluded.image_url,
                    notes=excluded.notes,
                    export_enabled=excluded.export_enabled,
                    updated_at=datetime('now')
                """,
                (
                    int(record.track_id),
                    record.status.strip(),
                    record.product_classification.strip(),
                    1 if bool(record.consumer_unit_flag) else 0,
                    record.packaging_type.strip(),
                    record.target_market.strip(),
                    record.language.strip(),
                    record.product_description.strip(),
                    record.brand.strip(),
                    record.subbrand.strip(),
                    record.quantity.strip(),
                    record.unit.strip(),
                    record.image_url.strip(),
                    record.notes.strip(),
                    1 if bool(record.export_enabled) else 0,
                    int(record.track_id),
                ),
            )
        saved = self.fetch_by_track_id(record.track_id)
        if saved is None:
            raise RuntimeError(f"Failed to save GS1 metadata for track {record.track_id}")
        return saved

