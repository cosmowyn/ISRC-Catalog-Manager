import tempfile
import unittest
import wave
from pathlib import Path

from mutagen.id3 import ID3
from mutagen.mp4 import MP4Cover

from isrc_manager.tags import ArtworkPayload, AudioTagData, catalog_metadata_to_tags, merge_imported_tags
from isrc_manager.tags.service import AudioTagService, TaggedAudioExportService


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


class AudioTagServiceTests(unittest.TestCase):
    def setUp(self):
        self.service = AudioTagService()
        self.tag_data = AudioTagData(
            title="Orbit",
            artist="Cosmowyn",
            album="Orbit Release",
            album_artist="Cosmowyn",
            track_number=2,
            disc_number=1,
            genre="Ambient",
            composer="M. van de Kleut",
            publisher="Cosmowyn Records",
            release_date="2026-03-15",
            isrc="NL-ABC-26-00002",
            upc="036000291452",
            comments="Catalog note",
            lyrics="wordless",
            artwork=ArtworkPayload(data=b"\x89PNGfake", mime_type="image/png"),
        )

    def test_catalog_metadata_to_tags_prefers_release_metadata(self):
        result = catalog_metadata_to_tags(
            track_values={
                "track_title": "Orbit",
                "artist_name": "Cosmowyn",
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
                "primary_artist": "Cosmowyn",
                "album_artist": "Cosmowyn Album Artist",
                "release_date": "2026-03-20",
                "label": "Release Label",
                "upc": "036000291452",
            },
            placement_values={"track_number": 7, "disc_number": 2},
        )

        self.assertEqual(result.album, "Orbit Release")
        self.assertEqual(result.album_artist, "Cosmowyn Album Artist")
        self.assertEqual(result.release_date, "2026-03-20")
        self.assertEqual(result.publisher, "Release Label")
        self.assertEqual(result.track_number, 7)
        self.assertEqual(result.disc_number, 2)

    def test_merge_imported_tags_can_prefer_file_tags(self):
        preview = merge_imported_tags(
            database_values={"title": "Database Title", "artist": "Database Artist", "artwork": None},
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
                exports=[(str(source_path), "orbit_export", self.tag_data)],
                progress_callback=lambda value, maximum, message: progress_updates.append((value, maximum, message)),
            )

        self.assertEqual(result.exported, 1)
        self.assertGreaterEqual(len(progress_updates), 2)
        self.assertEqual(progress_updates[0][0:2], (0, 1))
        self.assertEqual(progress_updates[-1][0:2], (1, 1))

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
                    exports=[(str(source_path), "orbit_export", self.tag_data)],
                    is_cancelled=lambda: True,
                )


if __name__ == "__main__":
    unittest.main()
