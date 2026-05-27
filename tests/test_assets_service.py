import sqlite3
from pathlib import Path
from unittest import mock

import pytest

from isrc_manager.assets.models import ASSET_TYPE_CHOICES, AssetVersionPayload
from isrc_manager.assets.service import AssetService
from isrc_manager.file_storage import STORAGE_MODE_DATABASE, STORAGE_MODE_MANAGED_FILE


def _create_asset_schema(conn: sqlite3.Connection, *, include_storage_columns: bool = True) -> None:
    cols = [
        "id INTEGER PRIMARY KEY AUTOINCREMENT",
        "asset_type TEXT",
        "filename TEXT",
        "stored_path TEXT",
    ]
    if include_storage_columns:
        cols.append("storage_mode TEXT")
    cols += [
        "track_id INTEGER",
        "release_id INTEGER",
        "checksum_sha256 TEXT",
        "duration_sec INTEGER",
        "sample_rate INTEGER",
        "bit_depth INTEGER",
        "format TEXT",
        "derived_from_asset_id INTEGER",
        "approved_for_use INTEGER",
        "primary_flag INTEGER",
        "version_status TEXT",
        "notes TEXT",
        "created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
        "updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
    ]
    if include_storage_columns:
        cols.insert(6, "file_blob BLOB")
    conn.executescript(f"CREATE TABLE AssetVersions (\n    {',\n    '.join(cols)}\n)")
    if include_storage_columns:
        return


@pytest.fixture()
def asset_service(tmp_path: Path) -> tuple[AssetService, sqlite3.Connection]:
    conn = sqlite3.connect(":memory:")
    _create_asset_schema(conn)
    service = AssetService(conn, data_root=tmp_path)
    yield service, conn
    conn.close()


def test_asset_type_cleaning_and_payload_defaults(
    asset_service: tuple[AssetService, sqlite3.Connection],
) -> None:
    service, _ = asset_service

    assert service._clean_type("Main Master") == "main_master"
    assert service._clean_type("  unknown   ") == "other"
    assert service._asset_subdir("art.png") == "images"
    assert service._asset_subdir("track.flac") == "audio"
    assert service._asset_subdir("notes.txt") == "files"

    assert ASSET_TYPE_CHOICES.count("other") == 1


def test_build_asset_payload_requires_source_or_bytes(tmp_path: Path) -> None:
    conn = sqlite3.connect(":memory:")
    _create_asset_schema(conn)
    service = AssetService(conn, data_root=tmp_path)

    with pytest.raises(ValueError):
        service._build_asset_payload(filename="x.txt", storage_mode=STORAGE_MODE_MANAGED_FILE)

    conn.close()


def test_build_asset_payload_database_and_managed_modes(tmp_path: Path) -> None:
    conn = sqlite3.connect(":memory:")
    _create_asset_schema(conn)
    service = AssetService(conn, data_root=tmp_path)

    source = tmp_path / "source.wav"
    source.write_bytes(b"raw-audio")
    service._extract_media_metadata = lambda _path: {
        "duration_sec": 11,
        "sample_rate": 44_100,
        "bit_depth": 16,
    }

    stored_path, filename, data, mime, source_hint, duration, rate, depth = (
        service._build_asset_payload(
            source_path=source,
            storage_mode=STORAGE_MODE_DATABASE,
        )
    )
    assert stored_path is None
    assert source_hint is None
    assert data == b"raw-audio"
    assert mime == "audio/x-wav"
    assert duration == 11 and rate == 44_100 and depth == 16

    managed_stored_path, filename2, data2, mime2, source_hint2, _, _, _ = (
        service._build_asset_payload(
            source_path=source,
            storage_mode=STORAGE_MODE_MANAGED_FILE,
            filename="cover.png",
        )
    )
    assert managed_stored_path is not None
    assert managed_stored_path.startswith("asset_registry")
    assert data2 is None
    assert mime2 == "image/png"
    assert filename2 == "cover.png"
    assert source_hint2 == managed_stored_path

    saved = service.resolve_asset_path(managed_stored_path)
    assert saved is not None
    assert saved.exists()
    assert saved.read_bytes() == b"raw-audio"
    assert "images/" in managed_stored_path

    conn.close()


def test_create_and_update_asset_flow(
    asset_service: tuple[AssetService, sqlite3.Connection],
) -> None:
    service, conn = asset_service
    source_a = Path(service.asset_root) / "track_a.wav"
    source_b = Path(service.asset_root) / "track_b.wav"
    source_a.parent.mkdir(parents=True, exist_ok=True)
    source_a.write_bytes(b"first")
    source_b.write_bytes(b"second")
    service._extract_media_metadata = lambda _path: {
        "duration_sec": 8,
        "sample_rate": 48_000,
        "bit_depth": 24,
    }

    first_id = service.create_asset(
        AssetVersionPayload(
            asset_type="main_master",
            source_path=str(source_a),
            track_id=11,
            approved_for_use=True,
            primary_flag=False,
            version_status="approved",
        )
    )
    second_id = service.create_asset(
        AssetVersionPayload(
            asset_type="hi_res_master",
            source_path=str(source_b),
            track_id=11,
            approved_for_use=True,
            primary_flag=True,
            version_status="approved",
        )
    )

    assets = service.list_assets(track_id=11)
    assert {item.id for item in assets} == {first_id, second_id}
    assert {item.primary_flag for item in assets} == {False, True}

    service.update_asset(
        second_id,
        AssetVersionPayload(
            asset_type="hi_res_master",
            source_path=str(source_a),
            storage_mode=STORAGE_MODE_DATABASE,
            checksum_sha256="",
            approved_for_use=True,
            primary_flag=True,
            version_status="approved",
            track_id=11,
        ),
    )

    updated = service.fetch_asset(second_id)
    assert updated is not None
    assert updated.storage_mode == STORAGE_MODE_DATABASE
    assert updated.stored_path is None
    assert updated.checksum_sha256 is not None and len(updated.checksum_sha256) == 64

    file_bytes, mime_type = service.fetch_asset_bytes(second_id)
    assert file_bytes == b"first"
    assert mime_type == "audio/x-wav"

    with pytest.raises(ValueError):
        service.update_asset(
            9_999,
            AssetVersionPayload(
                asset_type="main_master",
                source_path=str(source_a),
                track_id=11,
            ),
        )


def test_convert_asset_storage_mode_round_trip(
    asset_service: tuple[AssetService, sqlite3.Connection],
) -> None:
    service, _ = asset_service
    source = Path(service.asset_root) / "track.wav"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(b"roundtrip")

    service._extract_media_metadata = lambda _path: {
        "duration_sec": None,
        "sample_rate": None,
        "bit_depth": None,
    }
    asset_id = service.create_asset(
        AssetVersionPayload(
            asset_type="instrumental",
            source_path=str(source),
            storage_mode=STORAGE_MODE_MANAGED_FILE,
            track_id=21,
            version_status="approved",
        )
    )
    original = service.fetch_asset(asset_id)
    assert original is not None
    assert original.storage_mode == STORAGE_MODE_MANAGED_FILE
    assert original.stored_path is not None
    db_record = service.convert_asset_storage_mode(asset_id, STORAGE_MODE_DATABASE)
    assert db_record.storage_mode == STORAGE_MODE_DATABASE
    assert db_record.stored_path is None
    pre_convert_path = service.resolve_asset_path(original.stored_path)
    assert pre_convert_path is not None
    assert not pre_convert_path.exists()

    back_to_file = service.convert_asset_storage_mode(asset_id, STORAGE_MODE_MANAGED_FILE)
    assert back_to_file.storage_mode == STORAGE_MODE_MANAGED_FILE
    assert back_to_file.stored_path is not None
    restored = service.fetch_asset(asset_id)
    assert restored is not None
    assert restored.stored_path is not None

    restored_bytes, restored_mime = service.fetch_asset_bytes(asset_id)
    assert restored_bytes == b"roundtrip"
    assert restored_mime == "audio/x-wav"


def test_validate_assets_reports_primary_and_missing_approved_master(
    asset_service: tuple[AssetService, sqlite3.Connection],
) -> None:
    service, conn = asset_service
    source = Path(service.asset_root) / "track.wav"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(b"data")

    first_id = service.create_asset(
        AssetVersionPayload(
            asset_type="main_master",
            source_path=str(source),
            storage_mode=STORAGE_MODE_MANAGED_FILE,
            track_id=31,
            approved_for_use=False,
            primary_flag=True,
            version_status="approved",
        )
    )
    second_id = service.create_asset(
        AssetVersionPayload(
            asset_type="hi_res_master",
            source_path=str(source),
            storage_mode=STORAGE_MODE_MANAGED_FILE,
            track_id=31,
            approved_for_use=False,
            primary_flag=True,
            version_status="approved",
        )
    )

    conn.execute(
        "UPDATE AssetVersions SET primary_flag=1 WHERE id IN (?, ?)", (first_id, second_id)
    )
    conn.commit()

    issues = service.validate_assets()
    issue_types = {issue.issue_type for issue in issues}
    assert "duplicate_primary_asset" in issue_types
    assert "missing_approved_master" in issue_types

    first = service.fetch_asset(first_id)
    assert first is not None
    bad_path = service.resolve_asset_path(first.stored_path)
    assert bad_path is not None
    bad_path.unlink()

    still_there_issues = service.validate_assets()
    issue_map = {(item.issue_type, item.asset_id): item.message for item in still_there_issues}
    assert any(kind == "broken_asset_reference" for kind, _ in issue_map)


def test_mark_primary_and_fetch_and_delete(
    asset_service: tuple[AssetService, sqlite3.Connection],
) -> None:
    service, conn = asset_service
    source = Path(service.asset_root) / "track.wav"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(b"del")

    asset_id = service.create_asset(
        AssetVersionPayload(
            asset_type="main_master",
            source_path=str(source),
            track_id=99,
            version_status="approved",
            primary_flag=True,
        )
    )
    assert service.fetch_asset(asset_id) is not None

    with pytest.raises(ValueError):
        service.mark_primary(1_000)

    service.delete_asset(asset_id)
    assert service.fetch_asset(asset_id) is None
    row = conn.execute("SELECT COUNT(*) FROM AssetVersions WHERE id=?", (asset_id,)).fetchone()
    assert row is not None
    assert row[0] == 0

    deleted = service.resolve_asset_path(None)
    assert deleted is None


def test_ensure_storage_columns_adds_missing_columns(tmp_path: Path) -> None:
    conn = sqlite3.connect(":memory:")
    _create_asset_schema(conn, include_storage_columns=False)

    class _LegacyService(AssetService):
        pass

    _LegacyService(conn, data_root=tmp_path)  # noqa: B018
    cols = {str(row[1]) for row in conn.execute("PRAGMA table_info(AssetVersions)").fetchall()}
    assert "storage_mode" in cols
    assert "file_blob" in cols
    conn.close()


def test_asset_failure_and_noop_edges(tmp_path: Path) -> None:
    conn = sqlite3.connect(":memory:")
    _create_asset_schema(conn)
    service = AssetService(conn, data_root=tmp_path)

    empty_conn = sqlite3.connect(":memory:")
    try:
        assert (
            AssetService(empty_conn).sync_track_audio_attachment(
                track_id=1,
                source_path=tmp_path / "missing.wav",
                storage_mode=STORAGE_MODE_MANAGED_FILE,
            )
            is None
        )
    finally:
        empty_conn.close()

    with pytest.raises(ValueError, match="either a track or a release"):
        service.create_asset(AssetVersionPayload(asset_type="other", filename="loose.txt"))

    source = tmp_path / "asset.bin"
    source.write_bytes(b"asset-bytes")
    unconfigured = AssetService(conn, data_root=None)
    with pytest.raises(ValueError, match="not configured"):
        unconfigured._build_asset_payload(
            data=b"payload",
            filename="payload.bin",
            storage_mode=STORAGE_MODE_MANAGED_FILE,
        )

    with pytest.raises(FileNotFoundError):
        service.create_asset(
            AssetVersionPayload(
                asset_type="other",
                filename="missing.bin",
                stored_path="asset_registry/files/missing.bin",
                storage_mode=STORAGE_MODE_DATABASE,
                track_id=1,
            )
        )

    conn.execute(
        """
        INSERT INTO AssetVersions(asset_type, filename, storage_mode, file_blob, track_id)
        VALUES ('other', 'missing.bin', 'database', NULL, 1)
        """
    )
    missing_blob_id = int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])
    with pytest.raises(FileNotFoundError, match="no database blob"):
        service.fetch_asset_bytes(missing_blob_id)

    asset_id = service.create_asset(
        AssetVersionPayload(
            asset_type="other",
            source_path=str(source),
            storage_mode=STORAGE_MODE_DATABASE,
            track_id=2,
        )
    )
    before = service.fetch_asset(asset_id)
    assert before is not None
    assert service.convert_asset_storage_mode(asset_id, STORAGE_MODE_DATABASE) == before
    with pytest.raises(ValueError, match="Asset not found"):
        service.convert_asset_storage_mode(999, STORAGE_MODE_DATABASE)

    conn.close()


def test_delete_unreferenced_asset_file_paths(tmp_path: Path) -> None:
    conn = sqlite3.connect(":memory:")
    _create_asset_schema(conn)
    service = AssetService(conn, data_root=tmp_path)
    referenced = service.asset_store.write_bytes(
        b"referenced",
        filename="keep.bin",
        subdir="files",
    )
    orphaned = service.asset_store.write_bytes(
        b"orphaned",
        filename="remove.bin",
        subdir="files",
    )

    referenced_path = service.resolve_asset_path(referenced)
    orphaned_path = service.resolve_asset_path(orphaned)
    assert referenced_path is not None and orphaned_path is not None

    service.conn.execute(
        """
        INSERT INTO AssetVersions (
            asset_type,
            filename,
            stored_path,
            storage_mode,
            track_id,
            approved_for_use,
            primary_flag,
            version_status
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "other",
            "keep.bin",
            referenced,
            STORAGE_MODE_MANAGED_FILE,
            11,
            0,
            0,
            "approved",
        ),
    )

    with conn:
        service._delete_unreferenced_asset_file(None, cursor=conn.cursor())
        service._delete_unreferenced_asset_file(str(Path("/tmp/outside.bin")), cursor=conn.cursor())
        service._delete_unreferenced_asset_file(
            referenced,
            cursor=conn.cursor(),
        )
    assert referenced_path.exists()

    service._delete_unreferenced_asset_file(orphaned, cursor=conn.cursor())
    assert not orphaned_path.exists()

    conn.close()


def test_extract_media_metadata_defaults_when_mutagen_fails(tmp_path: Path) -> None:
    conn = sqlite3.connect(":memory:")
    _create_asset_schema(conn)
    service = AssetService(conn, data_root=tmp_path)

    source = tmp_path / "corrupt.bin"
    source.write_bytes(b"not-audio")

    with mock.patch("isrc_manager.assets.service.MutagenFile", side_effect=RuntimeError("boom")):
        metadata = service._extract_media_metadata(source)

    assert metadata == {
        "duration_sec": None,
        "sample_rate": None,
        "bit_depth": None,
    }

    conn.close()


def test_managed_asset_bytes_missing_source_raises(tmp_path: Path) -> None:
    conn = sqlite3.connect(":memory:")
    _create_asset_schema(conn)
    service = AssetService(conn, data_root=tmp_path)

    with pytest.raises(FileNotFoundError):
        service._managed_asset_bytes(tmp_path / "never-exists.bin")

    conn.close()


def test_build_asset_payload_without_source_uses_managed_file_mode_and_defaults(
    tmp_path: Path,
) -> None:
    conn = sqlite3.connect(":memory:")
    _create_asset_schema(conn)
    service = AssetService(conn, data_root=tmp_path)

    stored_path, filename, data, mime_type, source_hint, duration, sample_rate, bit_depth = (
        service._build_asset_payload(data=b"inline-bytes")
    )

    assert stored_path is not None
    assert filename == "asset"
    assert data is None
    assert source_hint == stored_path
    assert mime_type == ""
    assert duration is None
    assert sample_rate is None
    assert bit_depth is None

    conn.close()


def test_create_asset_legacy_stored_path_database_mode(tmp_path: Path) -> None:
    conn = sqlite3.connect(":memory:")
    _create_asset_schema(conn)
    service = AssetService(conn, data_root=tmp_path)

    legacy_source_path = service.asset_store.write_bytes(
        b"legacy bytes",
        filename="legacy.bin",
        subdir="files",
    )
    legacy_full_path = service.resolve_asset_path(legacy_source_path)
    assert legacy_full_path is not None

    asset_id = service.create_asset(
        AssetVersionPayload(
            asset_type="other",
            filename="legacy.bin",
            stored_path=legacy_source_path,
            storage_mode=STORAGE_MODE_DATABASE,
            track_id=61,
        )
    )

    asset = service.fetch_asset(asset_id)
    assert asset is not None
    assert asset.storage_mode == STORAGE_MODE_DATABASE
    assert asset.stored_path == legacy_source_path
    blob_bytes, _ = service.fetch_asset_bytes(asset_id)
    assert blob_bytes == b"legacy bytes"
    assert legacy_full_path.exists()

    conn.close()


def test_update_asset_mode_conversions_no_source_payload(tmp_path: Path) -> None:
    conn = sqlite3.connect(":memory:")
    _create_asset_schema(conn)
    service = AssetService(conn, data_root=tmp_path)
    source = tmp_path / "managed.wav"
    source.write_bytes(b"managed-content")
    service._extract_media_metadata = lambda _path: {
        "duration_sec": None,
        "sample_rate": None,
        "bit_depth": None,
    }

    asset_id = service.create_asset(
        AssetVersionPayload(
            asset_type="other",
            source_path=str(source),
            storage_mode=STORAGE_MODE_MANAGED_FILE,
            track_id=71,
        )
    )
    service.update_asset(
        asset_id,
        AssetVersionPayload(
            asset_type="other",
            filename="managed.wav",
            storage_mode=STORAGE_MODE_DATABASE,
            track_id=71,
        ),
    )
    updated = service.fetch_asset(asset_id)
    assert updated is not None
    assert updated.storage_mode == STORAGE_MODE_DATABASE

    asset_id2 = service.create_asset(
        AssetVersionPayload(
            asset_type="other",
            source_path=str(source),
            storage_mode=STORAGE_MODE_DATABASE,
            track_id=72,
        )
    )
    service.update_asset(
        asset_id2,
        AssetVersionPayload(
            asset_type="other",
            filename="restored.bin",
            storage_mode=STORAGE_MODE_MANAGED_FILE,
            track_id=72,
        ),
    )
    updated2 = service.fetch_asset(asset_id2)
    assert updated2 is not None
    assert updated2.storage_mode == STORAGE_MODE_MANAGED_FILE
    assert updated2.stored_path is not None
    restored_file = service.resolve_asset_path(updated2.stored_path)
    assert restored_file is not None
    assert restored_file.exists()
    assert updated2.id == asset_id2

    conn.close()


def test_update_asset_raises_when_database_mode_missing_source_blob(tmp_path: Path) -> None:
    conn = sqlite3.connect(":memory:")
    _create_asset_schema(conn)
    service = AssetService(conn, data_root=tmp_path)

    source = tmp_path / "source.bin"
    source.write_bytes(b"database-bytes")
    asset_id = service.create_asset(
        AssetVersionPayload(
            asset_type="other",
            source_path=str(source),
            storage_mode=STORAGE_MODE_DATABASE,
            track_id=73,
        )
    )
    missing_path = tmp_path / "missing-db-source.bin"
    assert not missing_path.exists()
    service.conn.execute(
        """
        UPDATE AssetVersions
        SET file_blob=NULL,
            storage_mode=?,
            stored_path=?
        WHERE id=?
        """,
        (
            STORAGE_MODE_DATABASE,
            str(missing_path),
            asset_id,
        ),
    )
    conn.commit()

    with pytest.raises(FileNotFoundError):
        service.update_asset(
            asset_id,
            AssetVersionPayload(
                asset_type="other",
                filename="other.bin",
                storage_mode=STORAGE_MODE_DATABASE,
                track_id=73,
            ),
        )

    conn.close()
