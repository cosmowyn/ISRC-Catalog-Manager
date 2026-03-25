"""Global search and relationship explorer services."""

from __future__ import annotations

import json
import sqlite3

from isrc_manager.domain.repertoire import clean_text

from .models import GlobalSearchResult, RelationshipSection, SavedSearchRecord


class GlobalSearchService:
    """Runs lightweight cross-entity search over the local workspace."""

    _ENTITY_ORDER = {
        "work": 0,
        "track": 1,
        "release": 2,
        "contract": 3,
        "right": 4,
        "party": 5,
        "document": 6,
        "asset": 7,
    }

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    @staticmethod
    def _normalized_entity_types(entity_types: list[str] | None) -> set[str]:
        return {str(item).strip().lower() for item in (entity_types or []) if str(item).strip()}

    @classmethod
    def _sort_results(cls, results: list[GlobalSearchResult]) -> list[GlobalSearchResult]:
        return sorted(
            results,
            key=lambda item: (
                cls._ENTITY_ORDER.get(item.entity_type, 999),
                item.title.casefold(),
                int(item.entity_id),
            ),
        )

    def search(
        self,
        query_text: str,
        *,
        entity_types: list[str] | None = None,
        limit: int = 100,
    ) -> list[GlobalSearchResult]:
        clean_query = clean_text(query_text)
        if not clean_query:
            return []
        allowed = self._normalized_entity_types(entity_types)
        like = f"%{clean_query}%"
        results: list[GlobalSearchResult] = []

        def include(entity_type: str) -> bool:
            return not allowed or entity_type in allowed

        if include("work"):
            for row in self.conn.execute(
                """
                SELECT id, title, COALESCE(iswc, ''), COALESCE(work_status, '')
                FROM Works
                WHERE title LIKE ? OR COALESCE(iswc, '') LIKE ? OR COALESCE(alternate_titles, '') LIKE ?
                ORDER BY title, id
                LIMIT ?
                """,
                (like, like, like, int(limit)),
            ).fetchall():
                results.append(
                    GlobalSearchResult(
                        "work",
                        int(row[0]),
                        str(row[1] or ""),
                        str(row[2] or ""),
                        clean_text(row[3]),
                        str(row[1] or ""),
                    )
                )
        if include("track"):
            for row in self.conn.execute(
                """
                SELECT
                    t.id,
                    t.track_title,
                    COALESCE(a.name, ''),
                    COALESCE(t.isrc, ''),
                    COALESCE(t.repertoire_status, '')
                FROM Tracks t
                LEFT JOIN Artists a ON a.id = t.main_artist_id
                WHERE t.track_title LIKE ? OR COALESCE(a.name, '') LIKE ? OR COALESCE(t.isrc, '') LIKE ?
                ORDER BY t.track_title, t.id
                LIMIT ?
                """,
                (like, like, like, int(limit)),
            ).fetchall():
                results.append(
                    GlobalSearchResult(
                        "track",
                        int(row[0]),
                        str(row[1] or ""),
                        " / ".join(part for part in (row[2], row[3]) if part),
                        clean_text(row[4]),
                        str(row[1] or ""),
                    )
                )
        if include("release"):
            for row in self.conn.execute(
                """
                SELECT id, title, COALESCE(primary_artist, ''), COALESCE(upc, ''), COALESCE(repertoire_status, '')
                FROM Releases
                WHERE title LIKE ? OR COALESCE(primary_artist, '') LIKE ? OR COALESCE(upc, '') LIKE ?
                ORDER BY title, id
                LIMIT ?
                """,
                (like, like, like, int(limit)),
            ).fetchall():
                results.append(
                    GlobalSearchResult(
                        "release",
                        int(row[0]),
                        str(row[1] or ""),
                        " / ".join(part for part in (row[2], row[3]) if part),
                        clean_text(row[4]),
                        str(row[1] or ""),
                    )
                )
        if include("contract"):
            for row in self.conn.execute(
                """
                SELECT id, title, COALESCE(contract_type, ''), status
                FROM Contracts
                WHERE title LIKE ? OR COALESCE(contract_type, '') LIKE ? OR COALESCE(summary, '') LIKE ?
                ORDER BY title, id
                LIMIT ?
                """,
                (like, like, like, int(limit)),
            ).fetchall():
                results.append(
                    GlobalSearchResult(
                        "contract",
                        int(row[0]),
                        str(row[1] or ""),
                        str(row[2] or ""),
                        clean_text(row[3]),
                        str(row[1] or ""),
                    )
                )
        if include("right"):
            for row in self.conn.execute(
                """
                SELECT id, COALESCE(title, right_type), COALESCE(territory, ''), right_type
                FROM RightsRecords
                WHERE COALESCE(title, '') LIKE ? OR COALESCE(territory, '') LIKE ? OR right_type LIKE ?
                ORDER BY right_type, id
                LIMIT ?
                """,
                (like, like, like, int(limit)),
            ).fetchall():
                results.append(
                    GlobalSearchResult(
                        "right",
                        int(row[0]),
                        str(row[1] or ""),
                        str(row[2] or ""),
                        str(row[3] or ""),
                        str(row[1] or ""),
                    )
                )
        if include("party"):
            for row in self.conn.execute(
                """
                SELECT id, legal_name, COALESCE(display_name, ''), COALESCE(email, ''), party_type
                FROM Parties
                WHERE legal_name LIKE ? OR COALESCE(display_name, '') LIKE ? OR COALESCE(email, '') LIKE ?
                ORDER BY legal_name, id
                LIMIT ?
                """,
                (like, like, like, int(limit)),
            ).fetchall():
                results.append(
                    GlobalSearchResult(
                        "party",
                        int(row[0]),
                        str(row[1] or ""),
                        " / ".join(part for part in (row[2], row[3]) if part),
                        clean_text(row[4]),
                        str(row[1] or ""),
                    )
                )
        if include("document"):
            for row in self.conn.execute(
                """
                SELECT id, title, COALESCE(filename, ''), document_type
                FROM ContractDocuments
                WHERE title LIKE ? OR COALESCE(filename, '') LIKE ? OR document_type LIKE ?
                ORDER BY title, id
                LIMIT ?
                """,
                (like, like, like, int(limit)),
            ).fetchall():
                results.append(
                    GlobalSearchResult(
                        "document",
                        int(row[0]),
                        str(row[1] or ""),
                        str(row[2] or ""),
                        str(row[3] or ""),
                        str(row[1] or ""),
                    )
                )
        if include("asset"):
            for row in self.conn.execute(
                """
                SELECT id, filename, asset_type, COALESCE(version_status, '')
                FROM AssetVersions
                WHERE filename LIKE ? OR asset_type LIKE ? OR COALESCE(version_status, '') LIKE ?
                ORDER BY filename, id
                LIMIT ?
                """,
                (like, like, like, int(limit)),
            ).fetchall():
                results.append(
                    GlobalSearchResult(
                        "asset",
                        int(row[0]),
                        str(row[1] or ""),
                        str(row[2] or ""),
                        clean_text(row[3]),
                        str(row[1] or ""),
                    )
                )
        return self._sort_results(results)[:limit]

    def browse_default_view(
        self,
        entity_types: list[str] | None = None,
        *,
        limit: int = 100,
        preview_limit: int = 8,
    ) -> list[GlobalSearchResult]:
        allowed = self._normalized_entity_types(entity_types)
        total_limit = max(0, int(limit))
        preview_limit = max(0, int(preview_limit))
        results: list[GlobalSearchResult] = []

        def include(entity_type: str) -> bool:
            return not allowed or entity_type in allowed

        def extend(rows, factory) -> None:
            for row in rows:
                results.append(factory(row))

        if include("work"):
            extend(
                self.conn.execute(
                    """
                    SELECT id, title, COALESCE(iswc, ''), COALESCE(work_status, '')
                    FROM Works
                    ORDER BY title, id
                    LIMIT ?
                    """,
                    (preview_limit,),
                ).fetchall(),
                lambda row: GlobalSearchResult(
                    "work",
                    int(row[0]),
                    str(row[1] or ""),
                    str(row[2] or ""),
                    clean_text(row[3]),
                    str(row[1] or ""),
                ),
            )
        if include("track"):
            extend(
                self.conn.execute(
                    """
                    SELECT
                        t.id,
                        t.track_title,
                        COALESCE(a.name, ''),
                        COALESCE(t.isrc, ''),
                        COALESCE(t.repertoire_status, '')
                    FROM Tracks t
                    LEFT JOIN Artists a ON a.id = t.main_artist_id
                    ORDER BY t.track_title, t.id
                    LIMIT ?
                    """,
                    (preview_limit,),
                ).fetchall(),
                lambda row: GlobalSearchResult(
                    "track",
                    int(row[0]),
                    str(row[1] or ""),
                    " / ".join(part for part in (row[2], row[3]) if part),
                    clean_text(row[4]),
                    str(row[1] or ""),
                ),
            )
        if include("release"):
            extend(
                self.conn.execute(
                    """
                    SELECT id, title, COALESCE(primary_artist, ''), COALESCE(upc, ''), COALESCE(repertoire_status, '')
                    FROM Releases
                    ORDER BY title, id
                    LIMIT ?
                    """,
                    (preview_limit,),
                ).fetchall(),
                lambda row: GlobalSearchResult(
                    "release",
                    int(row[0]),
                    str(row[1] or ""),
                    " / ".join(part for part in (row[2], row[3]) if part),
                    clean_text(row[4]),
                    str(row[1] or ""),
                ),
            )
        if include("contract"):
            extend(
                self.conn.execute(
                    """
                    SELECT id, title, COALESCE(contract_type, ''), status
                    FROM Contracts
                    ORDER BY title, id
                    LIMIT ?
                    """,
                    (preview_limit,),
                ).fetchall(),
                lambda row: GlobalSearchResult(
                    "contract",
                    int(row[0]),
                    str(row[1] or ""),
                    str(row[2] or ""),
                    clean_text(row[3]),
                    str(row[1] or ""),
                ),
            )
        if include("right"):
            extend(
                self.conn.execute(
                    """
                    SELECT id, COALESCE(title, right_type), COALESCE(territory, ''), right_type
                    FROM RightsRecords
                    ORDER BY COALESCE(title, right_type), id
                    LIMIT ?
                    """,
                    (preview_limit,),
                ).fetchall(),
                lambda row: GlobalSearchResult(
                    "right",
                    int(row[0]),
                    str(row[1] or ""),
                    str(row[2] or ""),
                    str(row[3] or ""),
                    str(row[1] or ""),
                ),
            )
        if include("party"):
            extend(
                self.conn.execute(
                    """
                    SELECT id, legal_name, COALESCE(display_name, ''), COALESCE(email, ''), party_type
                    FROM Parties
                    ORDER BY legal_name, id
                    LIMIT ?
                    """,
                    (preview_limit,),
                ).fetchall(),
                lambda row: GlobalSearchResult(
                    "party",
                    int(row[0]),
                    str(row[1] or ""),
                    " / ".join(part for part in (row[2], row[3]) if part),
                    clean_text(row[4]),
                    str(row[1] or ""),
                ),
            )
        if include("document"):
            extend(
                self.conn.execute(
                    """
                    SELECT id, title, COALESCE(filename, ''), document_type
                    FROM ContractDocuments
                    ORDER BY title, id
                    LIMIT ?
                    """,
                    (preview_limit,),
                ).fetchall(),
                lambda row: GlobalSearchResult(
                    "document",
                    int(row[0]),
                    str(row[1] or ""),
                    str(row[2] or ""),
                    str(row[3] or ""),
                    str(row[1] or ""),
                ),
            )
        if include("asset"):
            extend(
                self.conn.execute(
                    """
                    SELECT id, filename, asset_type, COALESCE(version_status, '')
                    FROM AssetVersions
                    ORDER BY filename, id
                    LIMIT ?
                    """,
                    (preview_limit,),
                ).fetchall(),
                lambda row: GlobalSearchResult(
                    "asset",
                    int(row[0]),
                    str(row[1] or ""),
                    str(row[2] or ""),
                    clean_text(row[3]),
                    str(row[1] or ""),
                ),
            )
        return self._sort_results(results)[:total_limit]

    def save_search(self, name: str, query_text: str, entity_types: list[str] | None = None) -> int:
        clean_name = clean_text(name)
        clean_query = clean_text(query_text)
        if not clean_name or not clean_query:
            raise ValueError("Saved searches require both a name and a query.")
        payload = json.dumps(list(entity_types or []), ensure_ascii=True)
        with self.conn:
            cursor = self.conn.execute(
                """
                INSERT INTO SavedSearches(name, query_text, entity_types)
                VALUES (?, ?, ?)
                ON CONFLICT(name) DO UPDATE SET
                    query_text=excluded.query_text,
                    entity_types=excluded.entity_types,
                    updated_at=datetime('now')
                """,
                (clean_name, clean_query, payload),
            )
            saved_id = int(cursor.lastrowid or 0)
        if saved_id:
            return saved_id
        row = self.conn.execute(
            "SELECT id FROM SavedSearches WHERE name=?", (clean_name,)
        ).fetchone()
        return int(row[0]) if row else 0

    def list_saved_searches(self) -> list[SavedSearchRecord]:
        rows = self.conn.execute(
            """
            SELECT id, name, query_text, entity_types
            FROM SavedSearches
            ORDER BY name, id
            """
        ).fetchall()
        records: list[SavedSearchRecord] = []
        for row in rows:
            try:
                entity_types = list(json.loads(str(row[3] or "[]")))
            except Exception:
                entity_types = []
            records.append(
                SavedSearchRecord(
                    id=int(row[0]),
                    name=str(row[1] or ""),
                    query_text=str(row[2] or ""),
                    entity_types=[str(item) for item in entity_types],
                )
            )
        return records

    def delete_saved_search(self, saved_search_id: int) -> None:
        with self.conn:
            self.conn.execute("DELETE FROM SavedSearches WHERE id=?", (int(saved_search_id),))


class RelationshipExplorerService:
    """Builds linked-entity views for one selected catalog record."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    @staticmethod
    def _result(
        entity_type: str, entity_id: int, title: str, subtitle: str, status: str | None = None
    ) -> GlobalSearchResult:
        return GlobalSearchResult(entity_type, int(entity_id), title, subtitle, status, title)

    def describe_links(self, entity_type: str, entity_id: int) -> list[RelationshipSection]:
        entity_type = str(entity_type).strip().lower()
        entity_id = int(entity_id)
        if entity_type == "work":
            return self._for_work(entity_id)
        if entity_type == "track":
            return self._for_track(entity_id)
        if entity_type == "release":
            return self._for_release(entity_id)
        if entity_type == "contract":
            return self._for_contract(entity_id)
        if entity_type == "party":
            return self._for_party(entity_id)
        if entity_type == "right":
            return self._for_right(entity_id)
        if entity_type == "document":
            return self._for_document(entity_id)
        if entity_type == "asset":
            return self._for_asset(entity_id)
        return []

    def _work_track_rows(self, work_id: int) -> list[tuple[int, str, str]]:
        rows = self.conn.execute(
            """
            SELECT DISTINCT
                t.id,
                t.track_title,
                COALESCE(a.name, '') AS artist_name,
                CASE WHEN t.work_id=? THEN 0 ELSE 1 END AS authority_rank,
                COALESCE(wt.is_primary, 0) AS compatibility_primary
            FROM Tracks t
            LEFT JOIN Artists a ON a.id = t.main_artist_id
            LEFT JOIN WorkTrackLinks wt
              ON wt.track_id = t.id
             AND wt.work_id = ?
            WHERE t.work_id = ?
               OR (t.work_id IS NULL AND wt.work_id IS NOT NULL)
            ORDER BY authority_rank, compatibility_primary DESC, t.track_title, t.id
            """,
            (int(work_id), int(work_id), int(work_id)),
        ).fetchall()
        return [(int(row[0]), str(row[1] or ""), str(row[2] or "")) for row in rows]

    def _track_work_rows(self, track_id: int) -> list[tuple[int, str, str, str]]:
        rows = self.conn.execute(
            """
            SELECT DISTINCT
                w.id,
                w.title,
                COALESCE(w.iswc, '') AS iswc,
                COALESCE(w.work_status, '') AS work_status,
                CASE WHEN t.work_id = w.id THEN 0 ELSE 1 END AS authority_rank,
                COALESCE(wt.is_primary, 0) AS compatibility_primary
            FROM Tracks t
            LEFT JOIN WorkTrackLinks wt ON wt.track_id = t.id
            JOIN Works w ON w.id = COALESCE(t.work_id, wt.work_id)
            WHERE t.id=?
            ORDER BY authority_rank, compatibility_primary DESC, w.title, w.id
            """,
            (int(track_id),),
        ).fetchall()
        return [
            (int(row[0]), str(row[1] or ""), str(row[2] or ""), str(row[3] or ""))
            for row in rows
        ]

    def _for_work(self, work_id: int) -> list[RelationshipSection]:
        tracks = [
            self._result("track", row[0], row[1], row[2])
            for row in self._work_track_rows(work_id)
        ]
        parties = [
            self._result("party", row[0], row[1], row[2])
            for row in self.conn.execute(
                """
                SELECT DISTINCT p.id, COALESCE(p.display_name, p.legal_name), wc.role
                FROM WorkContributors wc
                JOIN Parties p ON p.id = wc.party_id
                WHERE wc.work_id=?
                ORDER BY p.legal_name
                """,
                (int(work_id),),
            ).fetchall()
        ]
        contracts = [
            self._result("contract", row[0], row[1], row[2], row[3])
            for row in self.conn.execute(
                """
                SELECT c.id, c.title, COALESCE(c.contract_type, ''), c.status
                FROM ContractWorkLinks cw
                JOIN Contracts c ON c.id = cw.contract_id
                WHERE cw.work_id=?
                ORDER BY c.title, c.id
                """,
                (int(work_id),),
            ).fetchall()
        ]
        rights = [
            self._result("right", row[0], row[1], row[2], row[3])
            for row in self.conn.execute(
                """
                SELECT id, COALESCE(title, right_type), COALESCE(territory, ''), right_type
                FROM RightsRecords
                WHERE work_id=?
                ORDER BY id
                """,
                (int(work_id),),
            ).fetchall()
        ]
        return [
            RelationshipSection("Tracks", tracks),
            RelationshipSection("Parties", parties),
            RelationshipSection("Contracts", contracts),
            RelationshipSection("Rights", rights),
        ]

    def _for_track(self, track_id: int) -> list[RelationshipSection]:
        works = [
            self._result("work", row[0], row[1], row[2], row[3])
            for row in self._track_work_rows(track_id)
        ]
        releases = [
            self._result("release", row[0], row[1], row[2], row[3])
            for row in self.conn.execute(
                """
                SELECT r.id, r.title, COALESCE(r.primary_artist, ''), COALESCE(r.repertoire_status, '')
                FROM ReleaseTracks rt
                JOIN Releases r ON r.id = rt.release_id
                WHERE rt.track_id=?
                ORDER BY rt.sequence_number, r.id
                """,
                (int(track_id),),
            ).fetchall()
        ]
        contracts = [
            self._result("contract", row[0], row[1], row[2], row[3])
            for row in self.conn.execute(
                """
                SELECT c.id, c.title, COALESCE(c.contract_type, ''), c.status
                FROM ContractTrackLinks ct
                JOIN Contracts c ON c.id = ct.contract_id
                WHERE ct.track_id=?
                ORDER BY c.title, c.id
                """,
                (int(track_id),),
            ).fetchall()
        ]
        rights = [
            self._result("right", row[0], row[1], row[2], row[3])
            for row in self.conn.execute(
                """
                SELECT id, COALESCE(title, right_type), COALESCE(territory, ''), right_type
                FROM RightsRecords
                WHERE track_id=?
                ORDER BY id
                """,
                (int(track_id),),
            ).fetchall()
        ]
        assets = [
            self._result("asset", row[0], row[1], row[2], row[3])
            for row in self.conn.execute(
                """
                SELECT id, filename, asset_type, COALESCE(version_status, '')
                FROM AssetVersions
                WHERE track_id=?
                ORDER BY primary_flag DESC, id
                """,
                (int(track_id),),
            ).fetchall()
        ]
        return [
            RelationshipSection("Works", works),
            RelationshipSection("Releases", releases),
            RelationshipSection("Contracts", contracts),
            RelationshipSection("Rights", rights),
            RelationshipSection("Assets", assets),
        ]

    def _for_release(self, release_id: int) -> list[RelationshipSection]:
        tracks = [
            self._result("track", row[0], row[1], row[2])
            for row in self.conn.execute(
                """
                SELECT t.id, t.track_title, COALESCE(a.name, '')
                FROM ReleaseTracks rt
                JOIN Tracks t ON t.id = rt.track_id
                LEFT JOIN Artists a ON a.id = t.main_artist_id
                WHERE rt.release_id=?
                ORDER BY rt.sequence_number, t.id
                """,
                (int(release_id),),
            ).fetchall()
        ]
        contracts = [
            self._result("contract", row[0], row[1], row[2], row[3])
            for row in self.conn.execute(
                """
                SELECT c.id, c.title, COALESCE(c.contract_type, ''), c.status
                FROM ContractReleaseLinks cr
                JOIN Contracts c ON c.id = cr.contract_id
                WHERE cr.release_id=?
                ORDER BY c.title, c.id
                """,
                (int(release_id),),
            ).fetchall()
        ]
        rights = [
            self._result("right", row[0], row[1], row[2], row[3])
            for row in self.conn.execute(
                """
                SELECT id, COALESCE(title, right_type), COALESCE(territory, ''), right_type
                FROM RightsRecords
                WHERE release_id=?
                ORDER BY id
                """,
                (int(release_id),),
            ).fetchall()
        ]
        assets = [
            self._result("asset", row[0], row[1], row[2], row[3])
            for row in self.conn.execute(
                """
                SELECT id, filename, asset_type, COALESCE(version_status, '')
                FROM AssetVersions
                WHERE release_id=?
                ORDER BY primary_flag DESC, id
                """,
                (int(release_id),),
            ).fetchall()
        ]
        return [
            RelationshipSection("Tracks", tracks),
            RelationshipSection("Contracts", contracts),
            RelationshipSection("Rights", rights),
            RelationshipSection("Assets", assets),
        ]

    def _for_contract(self, contract_id: int) -> list[RelationshipSection]:
        parties = [
            self._result("party", row[0], row[1], row[2])
            for row in self.conn.execute(
                """
                SELECT p.id, COALESCE(p.display_name, p.legal_name), cp.role_label
                FROM ContractParties cp
                JOIN Parties p ON p.id = cp.party_id
                WHERE cp.contract_id=?
                ORDER BY cp.is_primary DESC, p.legal_name
                """,
                (int(contract_id),),
            ).fetchall()
        ]
        works = [
            self._result("work", row[0], row[1], row[2])
            for row in self.conn.execute(
                """
                SELECT w.id, w.title, COALESCE(w.iswc, '')
                FROM ContractWorkLinks cw
                JOIN Works w ON w.id = cw.work_id
                WHERE cw.contract_id=?
                ORDER BY w.title
                """,
                (int(contract_id),),
            ).fetchall()
        ]
        tracks = [
            self._result("track", row[0], row[1], row[2])
            for row in self.conn.execute(
                """
                SELECT t.id, t.track_title, COALESCE(a.name, '')
                FROM ContractTrackLinks ct
                JOIN Tracks t ON t.id = ct.track_id
                LEFT JOIN Artists a ON a.id = t.main_artist_id
                WHERE ct.contract_id=?
                ORDER BY t.track_title
                """,
                (int(contract_id),),
            ).fetchall()
        ]
        releases = [
            self._result("release", row[0], row[1], row[2])
            for row in self.conn.execute(
                """
                SELECT r.id, r.title, COALESCE(r.primary_artist, '')
                FROM ContractReleaseLinks cr
                JOIN Releases r ON r.id = cr.release_id
                WHERE cr.contract_id=?
                ORDER BY r.title
                """,
                (int(contract_id),),
            ).fetchall()
        ]
        rights = [
            self._result("right", row[0], row[1], row[2], row[3])
            for row in self.conn.execute(
                """
                SELECT id, COALESCE(title, right_type), COALESCE(territory, ''), right_type
                FROM RightsRecords
                WHERE source_contract_id=?
                ORDER BY id
                """,
                (int(contract_id),),
            ).fetchall()
        ]
        documents = [
            self._result("document", row[0], row[1], row[2], row[3])
            for row in self.conn.execute(
                """
                SELECT id, title, COALESCE(filename, ''), document_type
                FROM ContractDocuments
                WHERE contract_id=?
                ORDER BY active_flag DESC, id DESC
                """,
                (int(contract_id),),
            ).fetchall()
        ]
        return [
            RelationshipSection("Parties", parties),
            RelationshipSection("Works", works),
            RelationshipSection("Tracks", tracks),
            RelationshipSection("Releases", releases),
            RelationshipSection("Rights", rights),
            RelationshipSection("Documents", documents),
        ]

    def _for_party(self, party_id: int) -> list[RelationshipSection]:
        works = [
            self._result("work", row[0], row[1], row[2], row[3])
            for row in self.conn.execute(
                """
                SELECT DISTINCT w.id, w.title, COALESCE(w.iswc, ''), wc.role
                FROM WorkContributors wc
                JOIN Works w ON w.id = wc.work_id
                WHERE wc.party_id=?
                ORDER BY w.title
                """,
                (int(party_id),),
            ).fetchall()
        ]
        contracts = [
            self._result("contract", row[0], row[1], row[2], row[3])
            for row in self.conn.execute(
                """
                SELECT c.id, c.title, COALESCE(c.contract_type, ''), c.status
                FROM ContractParties cp
                JOIN Contracts c ON c.id = cp.contract_id
                WHERE cp.party_id=?
                ORDER BY c.title
                """,
                (int(party_id),),
            ).fetchall()
        ]
        rights = [
            self._result("right", row[0], row[1], row[2], row[3])
            for row in self.conn.execute(
                """
                SELECT id, COALESCE(title, right_type), COALESCE(territory, ''), right_type
                FROM RightsRecords
                WHERE granted_by_party_id=? OR granted_to_party_id=? OR retained_by_party_id=?
                ORDER BY id
                """,
                (int(party_id), int(party_id), int(party_id)),
            ).fetchall()
        ]
        return [
            RelationshipSection("Works", works),
            RelationshipSection("Contracts", contracts),
            RelationshipSection("Rights", rights),
        ]

    def _for_right(self, right_id: int) -> list[RelationshipSection]:
        row = self.conn.execute(
            """
            SELECT
                work_id,
                track_id,
                release_id,
                source_contract_id,
                granted_by_party_id,
                granted_to_party_id,
                retained_by_party_id
            FROM RightsRecords
            WHERE id=?
            """,
            (int(right_id),),
        ).fetchone()
        if not row:
            return []
        sections: list[RelationshipSection] = []
        if row[0] is not None:
            work = self.conn.execute(
                "SELECT id, title, COALESCE(iswc, '') FROM Works WHERE id=?",
                (int(row[0]),),
            ).fetchone()
            if work:
                sections.append(
                    RelationshipSection(
                        "Work",
                        [self._result("work", work[0], work[1], work[2])],
                    )
                )
        if row[1] is not None:
            track = self.conn.execute(
                """
                SELECT t.id, t.track_title, COALESCE(a.name, '')
                FROM Tracks t
                LEFT JOIN Artists a ON a.id = t.main_artist_id
                WHERE t.id=?
                """,
                (int(row[1]),),
            ).fetchone()
            if track:
                sections.append(
                    RelationshipSection(
                        "Track",
                        [self._result("track", track[0], track[1], track[2])],
                    )
                )
        if row[2] is not None:
            release = self.conn.execute(
                "SELECT id, title, COALESCE(primary_artist, '') FROM Releases WHERE id=?",
                (int(row[2]),),
            ).fetchone()
            if release:
                sections.append(
                    RelationshipSection(
                        "Release",
                        [self._result("release", release[0], release[1], release[2])],
                    )
                )
        if row[3] is not None:
            contract = self.conn.execute(
                "SELECT id, title, COALESCE(contract_type, ''), status FROM Contracts WHERE id=?",
                (int(row[3]),),
            ).fetchone()
            if contract:
                sections.append(
                    RelationshipSection(
                        "Source Contract",
                        [
                            self._result(
                                "contract", contract[0], contract[1], contract[2], contract[3]
                            )
                        ],
                    )
                )
        parties: list[GlobalSearchResult] = []
        for raw_party_id in row[4:7]:
            if raw_party_id is None:
                continue
            party = self.conn.execute(
                "SELECT id, COALESCE(display_name, legal_name), party_type FROM Parties WHERE id=?",
                (int(raw_party_id),),
            ).fetchone()
            if party:
                result = self._result("party", party[0], party[1], "", party[2])
                if result not in parties:
                    parties.append(result)
        if parties:
            sections.append(RelationshipSection("Parties", parties))
        return sections

    def _for_document(self, document_id: int) -> list[RelationshipSection]:
        row = self.conn.execute(
            """
            SELECT c.id, c.title, COALESCE(c.contract_type, ''), c.status
            FROM ContractDocuments d
            JOIN Contracts c ON c.id = d.contract_id
            WHERE d.id=?
            """,
            (int(document_id),),
        ).fetchone()
        if not row:
            return []
        return [
            RelationshipSection(
                "Contract",
                [self._result("contract", row[0], row[1], row[2], row[3])],
            )
        ]

    def _for_asset(self, asset_id: int) -> list[RelationshipSection]:
        row = self.conn.execute(
            "SELECT track_id, release_id FROM AssetVersions WHERE id=?",
            (int(asset_id),),
        ).fetchone()
        if not row:
            return []
        sections: list[RelationshipSection] = []
        if row[0] is not None:
            sections.extend(self._for_track(int(row[0])))
        if row[1] is not None:
            sections.extend(self._for_release(int(row[1])))
        return sections
