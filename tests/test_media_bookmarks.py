from __future__ import annotations

import sqlite3

import pytest

from isrc_manager.media.bookmarks import (
    add_audio_bookmark,
    delete_audio_bookmark,
    delete_audio_bookmarks_for_track,
    ensure_audio_bookmark_schema,
    load_audio_bookmarks,
)


def _memory_connection(*, row_factory=sqlite3.Row) -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = row_factory
    conn.execute("CREATE TABLE Tracks(id INTEGER PRIMARY KEY)")
    conn.execute("INSERT INTO Tracks(id) VALUES (1)")
    conn.execute("INSERT INTO Tracks(id) VALUES (2)")
    return conn


def test_audio_bookmark_schema_upsert_sort_delete_and_track_cascade():
    conn = _memory_connection()
    try:
        bookmark = add_audio_bookmark(
            conn,
            "1",
            2500.6,
            duration_ms=2000,
            label=" Intro ",
        )
        assert bookmark.track_id == 1
        assert bookmark.position_ms == 2000
        assert bookmark.label == "Intro"

        updated = add_audio_bookmark(
            conn,
            1,
            9999,
            duration_ms=2000,
            label="Updated intro",
        )
        assert updated.id == bookmark.id
        assert updated.label == "Updated intro"

        earlier = add_audio_bookmark(conn, 1, 750, label="")
        assert [item.position_ms for item in load_audio_bookmarks(conn, 1)] == [750, 2000]

        assert delete_audio_bookmark(conn, earlier.id, track_id=2) == 0
        assert delete_audio_bookmark(conn, earlier.id, track_id=1) == 1
        assert [item.id for item in load_audio_bookmarks(conn, 1)] == [bookmark.id]

        add_audio_bookmark(conn, 1, 3000, label="Outro")
        conn.execute("DELETE FROM Tracks WHERE id=1")
        assert load_audio_bookmarks(conn, 1) == []
    finally:
        conn.close()


def test_audio_bookmarks_tuple_rows_invalid_inputs_and_bulk_delete():
    conn = _memory_connection(row_factory=None)
    try:
        with pytest.raises(ValueError, match="track_id"):
            load_audio_bookmarks(conn, "bad")
        with pytest.raises(ValueError, match="track_id"):
            add_audio_bookmark(conn, 0, 100)

        bookmark = add_audio_bookmark(conn, 2, "not-a-position", duration_ms="bad")
        assert bookmark.position_ms == 0
        assert bookmark.label == ""
        assert load_audio_bookmarks(conn, 2)[0] == bookmark

        assert delete_audio_bookmark(conn, "bad") == 0
        assert delete_audio_bookmark(conn, -1) == 0
        assert delete_audio_bookmark(conn, bookmark.id, track_id="bad") == 0
        assert delete_audio_bookmarks_for_track(conn, 2) == 1
        assert load_audio_bookmarks(conn, 2) == []
    finally:
        conn.close()


def test_add_audio_bookmark_raises_when_insert_cannot_be_reloaded():
    class _FakeCursor:
        rowcount = 0

        def __init__(self, *, rows=None, row=None):
            self._rows = rows or []
            self._row = row

        def fetchall(self):
            return self._rows

        def fetchone(self):
            return self._row

    class _FakeConnection:
        def __init__(self):
            self.selects_after_insert = 0

        def execute(self, sql, _params=()):
            if "sqlite_master" in sql:
                return _FakeCursor(rows=[])
            if "SELECT id, track_id, position_ms" in sql:
                self.selects_after_insert += 1
                return _FakeCursor(row=None)
            return _FakeCursor()

        def __enter__(self):
            return self

        def __exit__(self, _exc_type, _exc, _tb):
            return False

    conn = _FakeConnection()

    with pytest.raises(RuntimeError, match="audio bookmark was not saved"):
        add_audio_bookmark(conn, 1, 100)

    assert conn.selects_after_insert == 1


def test_audio_bookmark_schema_without_tracks_table_skips_delete_trigger():
    conn = sqlite3.connect(":memory:")
    try:
        ensure_audio_bookmark_schema(conn)
        trigger_count = conn.execute("""
            SELECT COUNT(*)
            FROM sqlite_master
            WHERE type='trigger' AND name='trg_tracks_audio_bookmarks_delete'
            """).fetchone()[0]
        assert trigger_count == 0
    finally:
        conn.close()
