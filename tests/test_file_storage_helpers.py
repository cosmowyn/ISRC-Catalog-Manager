from __future__ import annotations

from pathlib import Path

import pytest

from isrc_manager import file_storage


def test_storage_mode_normalization_and_inference_branches() -> None:
    assert file_storage.normalize_storage_mode(" db ") == file_storage.STORAGE_MODE_DATABASE
    assert (
        file_storage.normalize_storage_mode("managed file")
        == file_storage.STORAGE_MODE_MANAGED_FILE
    )
    assert file_storage.normalize_storage_mode("", default="fallback") == "fallback"
    with pytest.raises(ValueError, match="Unsupported storage mode"):
        file_storage.normalize_storage_mode("external")

    assert (
        file_storage.infer_storage_mode(explicit_mode="blob") == file_storage.STORAGE_MODE_DATABASE
    )
    assert (
        file_storage.infer_storage_mode(stored_path="media/song.wav")
        == file_storage.STORAGE_MODE_MANAGED_FILE
    )
    assert file_storage.infer_storage_mode(blob_value=b"") == file_storage.STORAGE_MODE_DATABASE
    assert file_storage.infer_storage_mode(default="fallback") == "fallback"


def test_filename_and_export_name_sanitizers_preserve_safe_fallbacks() -> None:
    assert file_storage.sanitize_filename("../bad:name?.mp3") == "bad_name.mp3"
    assert file_storage.sanitize_filename(".", default_stem="asset") == "asset"
    assert file_storage.sanitize_filename("...///", default_stem="asset") == "asset"
    assert file_storage.sanitize_export_basename("  Album   Title.  ") == "Album Title"
    assert file_storage.sanitize_export_basename('Bad<Name>:"/Track') == "Bad_Name_Track"
    assert file_storage.export_package_name("", default_stem="Release") == "Release"


def test_common_export_package_name_handles_unique_mixed_and_empty_values() -> None:
    assert (
        file_storage.common_export_package_name(["Album", " album "], mixed_stem="Mixed") == "Album"
    )
    assert (
        file_storage.common_export_package_name(["Alpha", "Beta"], mixed_stem="Mixed Releases")
        == "Mixed Releases"
    )
    assert (
        file_storage.common_export_package_name(["", None], default_stem="Fallback") == "Fallback"
    )


def test_deduplicate_and_resolve_export_targets(tmp_path: Path) -> None:
    existing = tmp_path / "export.wav"
    existing.write_text("one", encoding="utf-8")
    (tmp_path / "export (2).wav").write_text("two", encoding="utf-8")

    assert file_storage.deduplicate_export_path(existing) == tmp_path / "export (3).wav"
    assert (
        file_storage.resolve_file_export_target(
            tmp_path,
            default_name="Track Name.wav",
            default_suffix=".wav",
        )
        == tmp_path / "Track_Name.wav"
    )
    assert (
        file_storage.resolve_file_export_target(
            tmp_path / "chosen",
            default_name="ignored.wav",
            default_suffix="wav",
        )
        == tmp_path / "chosen.wav"
    )
    with pytest.raises(ValueError, match="required"):
        file_storage.resolve_file_export_target("", default_name="track.wav")


def test_resolve_directory_export_target_uses_safe_child_folder(tmp_path: Path) -> None:
    assert (
        file_storage.resolve_directory_export_target(tmp_path, default_name="Album: One")
        == tmp_path / "Album_ One"
    )
    assert (
        file_storage.resolve_directory_export_target(tmp_path / "new-folder", default_name="Album")
        == tmp_path / "new-folder"
    )
    with pytest.raises(ValueError, match="required"):
        file_storage.resolve_directory_export_target("", default_name="Album")


def test_coalesce_filename_mime_guess_blob_bytes_and_hash() -> None:
    assert file_storage.coalesce_filename("", stored_path="/tmp/song.wav") == "song.wav"
    assert (
        file_storage.coalesce_filename("", default_stem="audio", default_suffix=".wav")
        == "audio.wav"
    )
    assert file_storage.guess_mime_type("song.wav") == "audio/x-wav"
    assert file_storage.guess_mime_type("", fallback="application/octet-stream") == (
        "application/octet-stream"
    )
    assert file_storage.bytes_from_blob(None) == b""
    assert file_storage.bytes_from_blob(bytearray(b"abc")) == b"abc"
    assert file_storage.bytes_from_blob(memoryview(b"abc")) == b"abc"
    assert file_storage.bytes_from_blob([65, 66]) == b"AB"
    assert file_storage.sha256_digest(b"abc") == (
        "ba7816bf8f01cfea414140de5dae2223" "b00361a396177a9cb410ff61f20015ad"
    )


def test_managed_file_storage_resolve_and_managed_detection(tmp_path: Path) -> None:
    storage = file_storage.ManagedFileStorage(
        data_root=tmp_path,
        relative_root="managed/media",
    )
    managed_rel = "managed/media/song.wav"
    outside_rel = "other/song.wav"
    absolute = tmp_path / "absolute.wav"

    assert storage.root_path == tmp_path / "managed/media"
    assert storage.resolve(managed_rel) == tmp_path / managed_rel
    assert storage.resolve(str(absolute)) == absolute
    assert storage.resolve("") is None
    assert storage.is_managed(managed_rel) is True
    assert storage.is_managed(outside_rel) is False
    assert storage.is_managed(str(absolute)) is False

    unconfigured = file_storage.ManagedFileStorage(data_root=None, relative_root="managed")
    assert unconfigured.root_path is None
    assert unconfigured.resolve("managed/song.wav") is None
    assert unconfigured.is_managed("managed/song.wav") is False
    with pytest.raises(ValueError, match="not configured"):
        unconfigured.write_bytes(b"data", filename="song.wav")


def test_managed_file_storage_reuses_identical_files_and_deduplicates_collisions(
    monkeypatch,
    tmp_path: Path,
) -> None:
    storage = file_storage.ManagedFileStorage(
        data_root=tmp_path,
        relative_root="managed/media",
    )
    monkeypatch.setattr(
        file_storage,
        "sha256_digest",
        lambda _data: "abc123def4567890",
    )

    first = storage.write_bytes(b"first", filename="song.wav")
    duplicate = storage.write_bytes(b"first", filename="song.wav")
    collision = storage.write_bytes(b"second", filename="song.wav", subdir="albums")
    second_collision = storage.write_bytes(b"third", filename="song.wav", subdir="albums")

    assert duplicate == first
    assert first == "managed/media/abc123def456_song.wav"
    assert collision == "managed/media/albums/abc123def456_song.wav"
    assert second_collision == "managed/media/albums/abc123def456_song_2.wav"
    assert (tmp_path / second_collision).read_bytes() == b"third"
