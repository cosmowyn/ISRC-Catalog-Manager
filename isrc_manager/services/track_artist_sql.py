"""SQL helpers for Party-backed track artist authority."""

from __future__ import annotations

import sqlite3


def table_names(conn: sqlite3.Connection) -> set[str]:
    return {
        str(row[0])
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        if row and row[0]
    }


def table_columns(conn: sqlite3.Connection, table_name: str) -> set[str]:
    if table_name not in table_names(conn):
        return set()
    return {
        str(row[1]) for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall() if row and row[1]
    }


def uses_party_artist_authority(conn: sqlite3.Connection) -> bool:
    return (
        "Parties" in table_names(conn)
        and "main_artist_party_id" in table_columns(conn, "Tracks")
        and "party_id" in table_columns(conn, "TrackArtists")
    )


def artist_display_name_sql(alias: str) -> str:
    return (
        "COALESCE("
        f"NULLIF(trim({alias}.artist_name), ''), "
        f"NULLIF(trim({alias}.display_name), ''), "
        f"NULLIF(trim({alias}.company_name), ''), "
        f"NULLIF(trim({alias}.legal_name), ''), "
        f"'Party #' || {alias}.id"
        ")"
    )


def track_main_artist_join_sql(
    conn: sqlite3.Connection,
    *,
    track_alias: str = "t",
    artist_alias: str = "artist_record",
) -> tuple[str, str]:
    if uses_party_artist_authority(conn):
        return (
            f"LEFT JOIN Parties {artist_alias} ON {artist_alias}.id = {track_alias}.main_artist_party_id",
            artist_display_name_sql(artist_alias),
        )
    return (
        f"LEFT JOIN Artists {artist_alias} ON {artist_alias}.id = {track_alias}.main_artist_id",
        f"COALESCE({artist_alias}.name, '')",
    )


def track_additional_artists_expr(
    conn: sqlite3.Connection,
    *,
    track_id_expr: str = "t.id",
    track_artist_alias: str = "ta",
    artist_alias: str = "artist_record",
    separator: str = ", ",
) -> str:
    if uses_party_artist_authority(conn):
        return (
            "("
            "SELECT COALESCE(group_concat(name_value, "
            + repr(separator)
            + "), '') "
            "FROM ("
            f"SELECT {artist_display_name_sql(artist_alias)} AS name_value "
            f"FROM TrackArtists {track_artist_alias} "
            f"JOIN Parties {artist_alias} ON {artist_alias}.id = {track_artist_alias}.party_id "
            f"WHERE {track_artist_alias}.track_id = {track_id_expr} "
            f"AND {track_artist_alias}.role='additional' "
            "ORDER BY lower(name_value), name_value"
            ")"
            ")"
        )
    return (
        "("
        "SELECT COALESCE(group_concat(name_value, "
        + repr(separator)
        + "), '') "
        "FROM ("
        f"SELECT COALESCE({artist_alias}.name, '') AS name_value "
        f"FROM TrackArtists {track_artist_alias} "
        f"JOIN Artists {artist_alias} ON {artist_alias}.id = {track_artist_alias}.artist_id "
        f"WHERE {track_artist_alias}.track_id = {track_id_expr} "
        f"AND {track_artist_alias}.role='additional' "
        "ORDER BY lower(name_value), name_value"
        ")"
        ")"
    )
