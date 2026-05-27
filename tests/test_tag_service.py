import io
import tempfile
import unittest
import wave
from pathlib import Path
from unittest import mock

try:
    from mutagen.id3 import ID3
    from mutagen.mp4 import MP4Cover
except Exception:  # pragma: no cover - optional in constrained local test envs
    ID3 = None
    MP4Cover = None

from isrc_manager.tags import (
    ArtworkPayload,
    AudioTagData,
    BulkAudioAttachTrackCandidate,
    catalog_metadata_to_tags,
    merge_imported_tags,
)
from isrc_manager.tags import (
    service as tag_service_module,
)
from isrc_manager.tags.models import TaggedAudioExportItem
from isrc_manager.tags.service import (
    AudioTagService,
    BulkAudioAttachService,
    TaggedAudioExportService,
)


class _DummyID3Audio:
    def __init__(self):
        self.tags = None
        self.saved = False

    def add_tags(self):
        self.tags = ID3()

    def save(self):
        self.saved = True


class _DummyFlac(dict):
    def __init__(self):
        super().__init__()
        self.pictures = []
        self.saved = False

    def clear_pictures(self):
        self.pictures.clear()

    def add_picture(self, picture):
        self.pictures.append(picture)

    def save(self):
        self.saved = True


class _DummyVorbis(dict):
    def __init__(self):
        super().__init__()
        self.saved = False

    def save(self):
        self.saved = True


class _DummyMp4:
    def __init__(self):
        self.tags = {}
        self.saved = False

    def save(self):
        self.saved = True


class _StubAudioTagReader:
    def __init__(self, payloads=None):
        self.payloads = dict(payloads or {})

    def read_tags(self, file_path):
        payload = self.payloads.get(Path(file_path).name, AudioTagData())
        if isinstance(payload, Exception):
            raise payload
        return payload


@unittest.skipIf(ID3 is None or MP4Cover is None, "mutagen is not installed")
class AudioTagServiceTests(unittest.TestCase):
    def setUp(self):
        self.service = AudioTagService()
        self.tag_data = AudioTagData(
            title="Orbit",
            artist="Moonwake",
            album="Orbit Release",
            album_artist="Moonwake",
            track_number=2,
            disc_number=1,
            genre="Ambient",
            composer="M. van de Kleut",
            publisher="Moonwake Records",
            release_date="2026-03-15",
            isrc="NL-ABC-26-00002",
            upc="036000291452",
            comments="Catalog note",
            lyrics="wordless",
            artwork=ArtworkPayload(data=b"\x89PNGfake", mime_type="image/png"),
        )

    @staticmethod
    def _make_wav_bytes(frame_count: int = 22050) -> bytes:
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(44100)
            handle.writeframes(b"\x00\x00" * frame_count)
        return buffer.getvalue()

    def test_catalog_metadata_to_tags_prefers_release_metadata(self):
        result = catalog_metadata_to_tags(
            track_values={
                "track_title": "Orbit",
                "artist_name": "Moonwake",
                "album_title": "Legacy Album",
                "release_date": "2026-03-15",
                "genre": "Ambient",
                "composer": "Composer",
                "publisher": "Track Publisher",
                "isrc": "NL-ABC-26-00002",
                "upc": "123456789012",
                "comments": "Track comment",
                "lyrics": "Track lyric",
            },
            release_values={
                "title": "Orbit Release",
                "primary_artist": "Moonwake",
                "album_artist": "Moonwake Album Artist",
                "release_date": "2026-03-20",
                "label": "Release Label",
                "upc": "036000291452",
            },
            placement_values={"track_number": 7, "disc_number": 2},
        )

        self.assertEqual(result.album, "Orbit Release")
        self.assertEqual(result.album_artist, "Moonwake Album Artist")
        self.assertEqual(result.release_date, "2026-03-20")
        self.assertEqual(result.publisher, "Release Label")
        self.assertEqual(result.track_number, 7)
        self.assertEqual(result.disc_number, 2)

    def test_catalog_metadata_to_tags_prefers_stored_track_number(self):
        result = catalog_metadata_to_tags(
            track_values={
                "track_title": "Orbit",
                "artist_name": "Moonwake",
                "album_title": "Orbit Release",
                "track_number": 3,
            },
            release_values={"title": "Orbit Release"},
            placement_values={"track_number": 7, "disc_number": 2},
        )

        self.assertEqual(result.track_number, 3)
        self.assertEqual(result.disc_number, 2)

    def test_merge_imported_tags_can_prefer_file_tags(self):
        preview = merge_imported_tags(
            database_values={
                "title": "Database Title",
                "artist": "Database Artist",
                "artwork": None,
            },
            file_tags=AudioTagData(title="File Title", artist="File Artist"),
            policy="prefer_file_tags",
        )

        self.assertEqual(preview.patch.values["title"], "File Title")
        self.assertEqual(preview.patch.values["artist"], "File Artist")
        self.assertEqual(len(preview.conflicts), 2)

    def test_id3_round_trip_with_dummy_audio(self):
        audio = _DummyID3Audio()
        self.service._write_id3_tags(audio, self.tag_data)
        reread = self.service._read_id3_tags(audio)

        self.assertTrue(audio.saved)
        self.assertEqual(reread.title, self.tag_data.title)
        self.assertEqual(reread.artist, self.tag_data.artist)
        self.assertEqual(reread.album, self.tag_data.album)
        self.assertEqual(reread.track_number, self.tag_data.track_number)
        self.assertEqual(reread.isrc, self.tag_data.isrc)
        self.assertEqual(reread.upc, self.tag_data.upc)
        self.assertEqual(reread.comments, self.tag_data.comments)

    def test_flac_like_round_trip(self):
        audio = _DummyFlac()
        self.service._write_flac_tags(audio, self.tag_data)
        reread = self.service._read_flac_tags(audio)

        self.assertTrue(audio.saved)
        self.assertEqual(reread.album_artist, self.tag_data.album_artist)
        self.assertEqual(reread.publisher, self.tag_data.publisher)
        self.assertEqual(reread.upc, self.tag_data.upc)
        self.assertIsNotNone(reread.artwork)

    def test_vorbis_like_round_trip(self):
        audio = _DummyVorbis()
        self.service._write_vorbis_like_tags(audio, self.tag_data)
        reread = self.service._read_vorbis_like_tags(audio)

        self.assertTrue(audio.saved)
        self.assertEqual(reread.title, self.tag_data.title)
        self.assertEqual(reread.genre, self.tag_data.genre)
        self.assertEqual(reread.isrc, self.tag_data.isrc)

    def test_mp4_like_round_trip(self):
        audio = _DummyMp4()
        self.service._write_mp4_tags(audio, self.tag_data)
        reread = self.service._read_mp4_tags(audio)

        self.assertTrue(audio.saved)
        self.assertEqual(reread.title, self.tag_data.title)
        self.assertEqual(reread.album, self.tag_data.album)
        self.assertEqual(reread.track_number, self.tag_data.track_number)
        self.assertEqual(reread.publisher, self.tag_data.publisher)
        self.assertEqual(reread.upc, self.tag_data.upc)
        self.assertIsInstance(audio.tags["covr"][0], MP4Cover)

    def test_wav_round_trip(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            wav_path = Path(tmpdir) / "sample.wav"
            with wave.open(str(wav_path), "wb") as handle:
                handle.setnchannels(1)
                handle.setsampwidth(2)
                handle.setframerate(44100)
                handle.writeframes(b"\x00\x00" * 44100)

            self.service.write_tags(wav_path, self.tag_data)
            reread = self.service.read_tags(wav_path)

        self.assertEqual(reread.title, self.tag_data.title)
        self.assertEqual(reread.artist, self.tag_data.artist)
        self.assertEqual(reread.isrc, self.tag_data.isrc)
        self.assertEqual(reread.upc, self.tag_data.upc)

    def test_tagged_audio_export_copies_managed_file_and_preserves_source(self):
        export_service = TaggedAudioExportService(self.service)
        with tempfile.TemporaryDirectory() as tmpdir:
            source_path = Path(tmpdir) / "sample.wav"
            with wave.open(str(source_path), "wb") as handle:
                handle.setnchannels(1)
                handle.setsampwidth(2)
                handle.setframerate(44100)
                handle.writeframes(b"\x00\x00" * 22050)

            original_bytes = source_path.read_bytes()
            result = export_service.export_copies(
                output_dir=Path(tmpdir) / "exports",
                exports=[
                    TaggedAudioExportItem(
                        suggested_name="orbit_export.mp3",
                        tag_data=self.tag_data,
                        source_path=source_path,
                        source_suffix=".wav",
                    )
                ],
            )
            exported_path = Path(result.written_paths[0])
            exported_tags = self.service.read_tags(exported_path)
            self.assertEqual(source_path.read_bytes(), original_bytes)

        self.assertEqual(result.exported, 1)
        self.assertEqual(exported_path.name, "orbit_export.wav")
        self.assertEqual(exported_tags.title, self.tag_data.title)
        self.assertEqual(exported_tags.isrc, self.tag_data.isrc)

    def test_tagged_audio_export_copies_byte_backed_source(self):
        export_service = TaggedAudioExportService(self.service)
        with tempfile.TemporaryDirectory() as tmpdir:
            result = export_service.export_copies(
                output_dir=Path(tmpdir) / "exports",
                exports=[
                    TaggedAudioExportItem(
                        suggested_name="blob_export.mp3",
                        tag_data=self.tag_data,
                        source_bytes=self._make_wav_bytes(),
                        source_suffix=".wav",
                    )
                ],
            )
            exported_path = Path(result.written_paths[0])
            exported_tags = self.service.read_tags(exported_path)

        self.assertEqual(result.exported, 1)
        self.assertEqual(exported_path.name, "blob_export.wav")
        self.assertEqual(exported_tags.artist, self.tag_data.artist)
        self.assertEqual(exported_tags.isrc, self.tag_data.isrc)

    def test_tagged_audio_export_reports_progress(self):
        export_service = TaggedAudioExportService(self.service)
        with tempfile.TemporaryDirectory() as tmpdir:
            source_path = Path(tmpdir) / "sample.wav"
            with wave.open(str(source_path), "wb") as handle:
                handle.setnchannels(1)
                handle.setsampwidth(2)
                handle.setframerate(44100)
                handle.writeframes(b"\x00\x00" * 22050)

            progress_updates = []
            result = export_service.export_copies(
                output_dir=Path(tmpdir) / "exports",
                exports=[
                    TaggedAudioExportItem(
                        suggested_name="orbit_export.mp3",
                        tag_data=self.tag_data,
                        source_path=source_path,
                        source_suffix=".wav",
                    )
                ],
                progress_callback=lambda value, maximum, message: progress_updates.append(
                    (value, maximum, message)
                ),
            )

        self.assertEqual(result.exported, 1)
        self.assertEqual(
            progress_updates,
            [
                (0, 3, "Resolving export source 1 of 1: orbit_export.mp3"),
                (1, 3, "Copying audio 1 of 1: orbit_export.mp3"),
                (2, 3, "Writing catalog metadata 1 of 1: orbit_export.mp3"),
            ],
        )
        self.assertEqual([value for value, _maximum, _message in progress_updates], [0, 1, 2])
        self.assertTrue(all(maximum == 3 for _value, maximum, _message in progress_updates))
        self.assertLess(progress_updates[-1][0], progress_updates[-1][1])

    def test_tagged_audio_export_can_be_cancelled(self):
        export_service = TaggedAudioExportService(self.service)
        with tempfile.TemporaryDirectory() as tmpdir:
            source_path = Path(tmpdir) / "sample.wav"
            with wave.open(str(source_path), "wb") as handle:
                handle.setnchannels(1)
                handle.setsampwidth(2)
                handle.setframerate(44100)
                handle.writeframes(b"\x00\x00" * 22050)

            with self.assertRaises(InterruptedError):
                export_service.export_copies(
                    output_dir=Path(tmpdir) / "exports",
                    exports=[
                        TaggedAudioExportItem(
                            suggested_name="orbit_export.mp3",
                            tag_data=self.tag_data,
                            source_path=source_path,
                            source_suffix=".wav",
                        )
                    ],
                    is_cancelled=lambda: True,
                )

    def test_tagged_audio_export_keeps_output_when_metadata_embedding_is_skipped(self):
        export_service = TaggedAudioExportService(self.service)
        with tempfile.TemporaryDirectory() as tmpdir:
            source_path = Path(tmpdir) / "sample.wav"
            with wave.open(str(source_path), "wb") as handle:
                handle.setnchannels(1)
                handle.setsampwidth(2)
                handle.setframerate(44100)
                handle.writeframes(b"\x00\x00" * 22050)

            with mock.patch.object(
                export_service.tag_service,
                "write_tags",
                side_effect=RuntimeError("tag write failed"),
            ):
                result = export_service.export_copies(
                    output_dir=Path(tmpdir) / "exports",
                    exports=[
                        TaggedAudioExportItem(
                            suggested_name="orbit_export.mp3",
                            tag_data=self.tag_data,
                            source_path=source_path,
                            source_suffix=".wav",
                        )
                    ],
                )

            exported_path = Path(result.written_paths[0])
            self.assertEqual(result.exported, 1)
            self.assertEqual(result.skipped, 0)
            self.assertTrue(exported_path.exists())
            self.assertTrue(
                any("metadata embedding skipped" in warning for warning in result.warnings)
            )

    def test_service_helper_edges_cover_backend_and_mp4_family_guardrails(self):
        self.assertIsNone(tag_service_module._first(None))
        self.assertEqual(tag_service_module._first(["first", "second"]), "first")
        self.assertEqual(tag_service_module._first([], default="fallback"), "fallback")
        self.assertIsNone(tag_service_module._parse_slashed_number("bad/value"))
        self.assertIsNone(tag_service_module._clean_filename_title_token("   "))
        self.assertEqual(tag_service_module._clean_filename_title_token("01 - Orbit"), "Orbit")
        self.assertEqual(TaggedAudioExportService._normalize_suffix("wav"), ".wav")
        self.assertEqual(TaggedAudioExportService._normalize_suffix(".flac"), ".flac")

        tuple_item = TaggedAudioExportService._coerce_export_item(
            ("/tmp/source.wav", "Source Name", AudioTagData(title="Tuple Title"))
        )
        self.assertEqual(tuple_item.source_suffix, ".wav")
        self.assertEqual(tuple_item.tag_data.title, "Tuple Title")

        service = AudioTagService()
        with mock.patch.object(tag_service_module, "MutagenFile", return_value=object()):
            with self.assertRaisesRegex(ValueError, "Raw AAC"):
                service._load_mp4_family_audio(Path("raw.aac"))
            with self.assertRaisesRegex(ValueError, "Unsupported MP4-family"):
                service._load_mp4_family_audio(Path("raw.m4a"))

        self.assertIsNone(AudioTagService._decode_base64_bytes(None))
        self.assertIsNone(AudioTagService._decode_base64_bytes(""))
        with mock.patch.object(tag_service_module.base64, "b64decode", side_effect=ValueError):
            self.assertIsNone(AudioTagService._decode_base64_bytes("Y292ZXI="))

    def test_vorbis_artwork_fallbacks_and_mp4_freeform_cleanup(self):
        class PicturePayload:
            data = b"picture"
            mime = ""
            desc = "front"

        audio = _DummyVorbis()
        audio.pictures = [PicturePayload()]
        artwork = AudioTagService._read_vorbis_like_artwork(audio)

        self.assertEqual(artwork.data, b"picture")
        self.assertEqual(artwork.mime_type, "image/jpeg")
        self.assertEqual(artwork.description, "front")

        coverart_audio = _DummyVorbis()
        coverart_audio["metadata_block_picture"] = ["not-valid-base64-picture"]
        coverart_audio["coverart"] = ["Y292ZXI="]
        coverart_audio["coverartmime"] = ["image/png"]
        coverart = AudioTagService._read_vorbis_like_artwork(coverart_audio)

        self.assertEqual(coverart.data, b"cover")
        self.assertEqual(coverart.mime_type, "image/png")

        tags = {"----:com.apple.iTunes:ISRC": [b"NL-ABC-26-00001"]}
        self.assertEqual(
            AudioTagService._decode_mp4_freeform(_DummyMp4WithTags(tags), "ISRC"), "NL-ABC-26-00001"
        )
        AudioTagService._set_mp4_freeform(tags, "ISRC", "")
        self.assertNotIn("----:com.apple.iTunes:ISRC", tags)


class BulkAudioAttachServiceTests(unittest.TestCase):
    def test_bulk_audio_attach_service_matches_by_filename_and_suggests_artist(self):
        service = BulkAudioAttachService(_StubAudioTagReader())
        with tempfile.TemporaryDirectory() as tmpdir:
            orbit_path = Path(tmpdir) / "Artist One - Orbit.wav"
            aurora_path = Path(tmpdir) / "Artist One - Aurora.wav"
            orbit_path.write_bytes(b"")
            aurora_path.write_bytes(b"")

            plan = service.build_plan(
                file_paths=[orbit_path, aurora_path],
                tracks=[
                    BulkAudioAttachTrackCandidate(track_id=1, title="Orbit", artist="Artist One"),
                    BulkAudioAttachTrackCandidate(track_id=2, title="Aurora", artist="Artist One"),
                ],
            )

        self.assertEqual([item.matched_track_id for item in plan.items], [1, 2])
        self.assertEqual(plan.suggested_artist, "Artist One")

    def test_bulk_audio_attach_service_marks_duplicate_matches_as_ambiguous(self):
        service = BulkAudioAttachService(_StubAudioTagReader())
        with tempfile.TemporaryDirectory() as tmpdir:
            exact_path = Path(tmpdir) / "Orbit.wav"
            weaker_path = Path(tmpdir) / "Orbit Live.wav"
            exact_path.write_bytes(b"")
            weaker_path.write_bytes(b"")

            plan = service.build_plan(
                file_paths=[exact_path, weaker_path],
                tracks=[BulkAudioAttachTrackCandidate(track_id=11, title="Orbit")],
            )

        self.assertEqual(plan.items[0].matched_track_id, 11)
        self.assertIsNone(plan.items[1].matched_track_id)
        self.assertEqual(plan.items[1].status, "ambiguous")

    def test_bulk_audio_attach_service_preserves_candidate_ids_for_ambiguous_title_ties(self):
        service = BulkAudioAttachService(_StubAudioTagReader())
        with tempfile.TemporaryDirectory() as tmpdir:
            ambiguous_path = Path(tmpdir) / "Orbit.wav"
            ambiguous_path.write_bytes(b"")

            plan = service.build_plan(
                file_paths=[ambiguous_path],
                tracks=[
                    BulkAudioAttachTrackCandidate(track_id=11, title="Orbit", artist="Artist One"),
                    BulkAudioAttachTrackCandidate(track_id=22, title="Orbit", artist="Artist Two"),
                ],
            )

        self.assertEqual(plan.items[0].status, "ambiguous")
        self.assertIsNone(plan.items[0].matched_track_id)
        self.assertEqual(plan.items[0].candidate_track_ids, [11, 22])

    def test_bulk_audio_attach_service_builds_import_plan_from_tags_and_filename(self):
        service = BulkAudioAttachService(
            _StubAudioTagReader(
                {
                    "01 - Orbit.wav": AudioTagData(
                        title="Orbit",
                        artist="Artist One",
                        album="Dawn Atlas",
                        track_number=1,
                        isrc="NL-C5X-26-00001",
                        composer="Writer One",
                        publisher="Publisher One",
                        artwork=ArtworkPayload(data=b"\x89PNGfake", mime_type="image/png"),
                    )
                }
            )
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            tagged_path = Path(tmpdir) / "01 - Orbit.wav"
            fallback_path = Path(tmpdir) / "Artist Two - Aurora.wav"
            tagged_path.write_bytes(b"")
            fallback_path.write_bytes(b"")

            plan = service.build_import_plan(file_paths=[tagged_path, fallback_path])

        self.assertEqual(plan.items[0].title, "Orbit")
        self.assertEqual(plan.items[0].artist, "Artist One")
        self.assertEqual(plan.items[0].album, "Dawn Atlas")
        self.assertEqual(plan.items[0].track_number, 1)
        self.assertEqual(plan.items[0].isrc, "NL-C5X-26-00001")
        self.assertEqual(plan.items[0].artwork.mime_type, "image/png")
        self.assertEqual(plan.items[1].title, "Aurora")
        self.assertEqual(plan.items[1].artist, "Artist Two")
        self.assertIsNone(plan.items[1].artwork)
        self.assertEqual(plan.suggested_artist, None)

    def test_bulk_audio_attach_service_reports_tag_read_warnings_and_progress(self):
        service = BulkAudioAttachService(
            _StubAudioTagReader(
                {
                    "Broken.wav": RuntimeError("cannot read tags"),
                    "Tagged.wav": AudioTagData(
                        title="Tagged",
                        artist="Artist One",
                        album_artist="Album Artist",
                        warnings=["embedded art skipped"],
                    ),
                }
            )
        )
        progress: list[tuple[int, int, str]] = []
        with tempfile.TemporaryDirectory() as tmpdir:
            broken_path = Path(tmpdir) / "Broken.wav"
            tagged_path = Path(tmpdir) / "Tagged.wav"
            broken_path.write_bytes(b"")
            tagged_path.write_bytes(b"")

            plan = service.build_import_plan(
                file_paths=[broken_path, tagged_path],
                progress_callback=lambda value, maximum, message: progress.append(
                    (value, maximum, message)
                ),
            )

        self.assertEqual(plan.items[0].title, "Broken")
        self.assertIn("Broken.wav: cannot read tags", plan.warnings[0])
        self.assertIn("embedded art skipped", plan.warnings[1])
        self.assertEqual(plan.suggested_artist, "Artist One")
        self.assertEqual(progress[-1], (2, 2, "Audio metadata import preview is ready."))

    def test_bulk_audio_attach_service_clears_equal_duplicate_matches(self):
        service = BulkAudioAttachService(_StubAudioTagReader())
        with tempfile.TemporaryDirectory() as tmpdir:
            first_path = Path(tmpdir) / "Orbit.wav"
            second_path = Path(tmpdir) / "01 - Orbit.wav"
            first_path.write_bytes(b"")
            second_path.write_bytes(b"")

            plan = service.build_plan(
                file_paths=[first_path, second_path],
                tracks=[BulkAudioAttachTrackCandidate(track_id=11, title="Orbit")],
            )

        self.assertEqual([item.status for item in plan.items], ["ambiguous", "ambiguous"])
        self.assertEqual([item.matched_track_id for item in plan.items], [None, None])
        self.assertTrue(
            all("Multiple files matched" in str(item.match_basis) for item in plan.items)
        )

    def test_bulk_audio_attach_service_scores_isrc_artist_and_empty_candidates(self):
        track = BulkAudioAttachTrackCandidate(
            track_id=42,
            title="Orbit",
            artist="Moonwake",
            isrc="NL-ABC-26-00042",
        )

        self.assertEqual(
            BulkAudioAttachService._score_match(
                track,
                title_candidates=[],
                detected_artist=None,
                tag_data=AudioTagData(isrc="NLABC2600042"),
            ),
            (420, "ISRC tag"),
        )
        self.assertEqual(
            BulkAudioAttachService._score_match(
                track,
                title_candidates=[("Orbit", "Title tag"), ("", "Filename")],
                detected_artist="Moonwake",
                tag_data=AudioTagData(),
            ),
            (285, "Title tag + artist"),
        )
        self.assertEqual(
            BulkAudioAttachService._suggest_artist(["One", "Two"]),
            None,
        )


class _DummyMp4WithTags:
    def __init__(self, tags):
        self.tags = tags


if __name__ == "__main__":
    unittest.main()
