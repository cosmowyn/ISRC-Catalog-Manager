"""Audio metadata tag reading and writing across common file formats."""

from __future__ import annotations

import shutil
from pathlib import Path

try:
    from mutagen import File as MutagenFile
    from mutagen.aiff import AIFF
    from mutagen.flac import FLAC, Picture
    from mutagen.id3 import (
        APIC,
        COMM,
        ID3,
        TALB,
        TCOM,
        TCON,
        TDRC,
        TIT2,
        TPE1,
        TPE2,
        TPOS,
        TPUB,
        TRCK,
        TSRC,
        TXXX,
        USLT,
    )
    from mutagen.mp3 import MP3
    from mutagen.mp4 import MP4, MP4Cover, MP4FreeForm
    from mutagen.oggopus import OggOpus
    from mutagen.oggvorbis import OggVorbis
    from mutagen.wave import WAVE
except ImportError:  # pragma: no cover - exercised indirectly in runtime packaging environments
    MutagenFile = None
    AIFF = None
    FLAC = None
    Picture = None
    ID3 = None
    APIC = COMM = TALB = TCOM = TCON = TDRC = TIT2 = TPE1 = TPE2 = TPOS = TPUB = TRCK = TSRC = (
        TXXX
    ) = USLT = None
    MP3 = None
    MP4 = MP4Cover = MP4FreeForm = None
    OggOpus = OggVorbis = None
    WAVE = None

from isrc_manager.domain.codes import normalize_isrc, to_iso_isrc

from .models import ArtworkPayload, AudioTagData, TaggedAudioExportResult


def _first(values, default=None):
    if values is None:
        return default
    if isinstance(values, list):
        return values[0] if values else default
    return values


def _clean_text(value) -> str | None:
    text = str(value or "").strip()
    return text or None


def _clean_isrc(value) -> str | None:
    text = _clean_text(value)
    if not text:
        return None
    return to_iso_isrc(text) or text


def _parse_slashed_number(value) -> int | None:
    text = _clean_text(value)
    if not text:
        return None
    try:
        return int(text.split("/", 1)[0])
    except Exception:
        return None


def _first_text(items) -> str | None:
    if not items:
        return None
    first_item = items[0]
    if isinstance(first_item, list):
        first_item = first_item[0] if first_item else None
    return _clean_text(first_item)


class AudioTagService:
    """Reads and writes canonical metadata tags with format-aware adapters."""

    @staticmethod
    def _ensure_backend() -> None:
        if MutagenFile is None:
            raise RuntimeError(
                "Audio tag support requires the 'mutagen' package. Install project dependencies and try again."
            )

    def read_tags(self, file_path: str | Path) -> AudioTagData:
        self._ensure_backend()
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(path)

        suffix = path.suffix.lower()
        if suffix == ".mp3":
            return self._read_id3_tags(MP3(path))
        if suffix == ".flac":
            return self._read_flac_tags(FLAC(path))
        if suffix in {".ogg", ".oga"}:
            try:
                return self._read_vorbis_like_tags(OggVorbis(path))
            except Exception:
                return self._read_vorbis_like_tags(OggOpus(path))
        if suffix == ".opus":
            return self._read_vorbis_like_tags(OggOpus(path))
        if suffix in {".m4a", ".mp4", ".aac"}:
            return self._read_mp4_tags(MP4(path))
        if suffix == ".wav":
            return self._read_id3_tags(WAVE(path))
        if suffix in {".aif", ".aiff"}:
            return self._read_id3_tags(AIFF(path))

        audio = MutagenFile(path, easy=False)
        if audio is None:
            raise ValueError(f"Unsupported audio tag format: {path.suffix}")
        if isinstance(audio, FLAC):
            return self._read_flac_tags(audio)
        if isinstance(audio, (OggVorbis, OggOpus)):
            return self._read_vorbis_like_tags(audio)
        if isinstance(audio, MP4):
            return self._read_mp4_tags(audio)
        return self._read_id3_tags(audio)

    def write_tags(self, file_path: str | Path, tag_data: AudioTagData) -> None:
        self._ensure_backend()
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(path)
        suffix = path.suffix.lower()
        if suffix == ".mp3":
            self._write_id3_tags(MP3(path), tag_data)
            return
        if suffix == ".flac":
            self._write_flac_tags(FLAC(path), tag_data)
            return
        if suffix in {".ogg", ".oga"}:
            try:
                self._write_vorbis_like_tags(OggVorbis(path), tag_data)
            except Exception:
                self._write_vorbis_like_tags(OggOpus(path), tag_data)
            return
        if suffix == ".opus":
            self._write_vorbis_like_tags(OggOpus(path), tag_data)
            return
        if suffix in {".m4a", ".mp4", ".aac"}:
            self._write_mp4_tags(MP4(path), tag_data)
            return
        if suffix == ".wav":
            self._write_id3_tags(WAVE(path), tag_data)
            return
        if suffix in {".aif", ".aiff"}:
            self._write_id3_tags(AIFF(path), tag_data)
            return
        raise ValueError(f"Unsupported audio tag format: {path.suffix}")

    def _read_id3_tags(self, audio) -> AudioTagData:
        try:
            tags = audio.tags or ID3()
        except Exception:
            tags = ID3(audio.filename)
        artwork = None
        apic_frames = tags.getall("APIC")
        if apic_frames:
            artwork = ArtworkPayload(
                data=bytes(apic_frames[0].data),
                mime_type=str(apic_frames[0].mime or "image/jpeg"),
                description=str(apic_frames[0].desc or ""),
            )
        comments = tags.getall("COMM")
        lyrics = tags.getall("USLT")
        return AudioTagData(
            title=_clean_text(tags.get("TIT2")),
            artist=_clean_text(tags.get("TPE1")),
            album=_clean_text(tags.get("TALB")),
            album_artist=_clean_text(tags.get("TPE2")),
            track_number=_parse_slashed_number(tags.get("TRCK")),
            disc_number=_parse_slashed_number(tags.get("TPOS")),
            genre=_clean_text(tags.get("TCON")),
            composer=_clean_text(tags.get("TCOM")),
            publisher=_clean_text(tags.get("TPUB")),
            release_date=_clean_text(tags.get("TDRC")),
            isrc=_clean_isrc(tags.get("TSRC")),
            upc=_clean_text(_first_text([frame.text for frame in tags.getall("TXXX:UPC")])),
            comments=_clean_text(_first_text([frame.text for frame in comments])),
            lyrics=_clean_text(_first_text([frame.text for frame in lyrics])),
            artwork=artwork,
            raw_fields={"format": "id3"},
        )

    def _write_id3_tags(self, audio, tag_data: AudioTagData) -> None:
        try:
            tags = audio.tags
            if tags is None:
                audio.add_tags()
                tags = audio.tags
        except Exception:
            audio.tags = ID3()
            tags = audio.tags

        tags.delall("TIT2")
        tags.delall("TPE1")
        tags.delall("TALB")
        tags.delall("TPE2")
        tags.delall("TRCK")
        tags.delall("TPOS")
        tags.delall("TCON")
        tags.delall("TCOM")
        tags.delall("TPUB")
        tags.delall("TDRC")
        tags.delall("TSRC")
        tags.delall("TXXX:UPC")
        tags.delall("COMM")
        tags.delall("USLT")
        tags.delall("APIC")

        if tag_data.title:
            tags.add(TIT2(encoding=3, text=[tag_data.title]))
        if tag_data.artist:
            tags.add(TPE1(encoding=3, text=[tag_data.artist]))
        if tag_data.album:
            tags.add(TALB(encoding=3, text=[tag_data.album]))
        if tag_data.album_artist:
            tags.add(TPE2(encoding=3, text=[tag_data.album_artist]))
        if tag_data.track_number:
            tags.add(TRCK(encoding=3, text=[str(tag_data.track_number)]))
        if tag_data.disc_number:
            tags.add(TPOS(encoding=3, text=[str(tag_data.disc_number)]))
        if tag_data.genre:
            tags.add(TCON(encoding=3, text=[tag_data.genre]))
        if tag_data.composer:
            tags.add(TCOM(encoding=3, text=[tag_data.composer]))
        if tag_data.publisher:
            tags.add(TPUB(encoding=3, text=[tag_data.publisher]))
        if tag_data.release_date:
            tags.add(TDRC(encoding=3, text=[tag_data.release_date]))
        if tag_data.isrc:
            tags.add(TSRC(encoding=3, text=[normalize_isrc(tag_data.isrc)]))
        if tag_data.upc:
            tags.add(TXXX(encoding=3, desc="UPC", text=[tag_data.upc]))
        if tag_data.comments:
            tags.add(COMM(encoding=3, lang="eng", desc="", text=[tag_data.comments]))
        if tag_data.lyrics:
            tags.add(USLT(encoding=3, lang="eng", desc="", text=tag_data.lyrics))
        if tag_data.artwork is not None:
            tags.add(
                APIC(
                    encoding=3,
                    mime=tag_data.artwork.mime_type or "image/jpeg",
                    type=3,
                    desc=tag_data.artwork.description or "",
                    data=tag_data.artwork.data,
                )
            )
        audio.save()

    def _read_flac_tags(self, audio: FLAC) -> AudioTagData:
        artwork = None
        if audio.pictures:
            picture = audio.pictures[0]
            artwork = ArtworkPayload(
                data=bytes(picture.data),
                mime_type=str(picture.mime or "image/jpeg"),
                description=str(picture.desc or ""),
            )
        return AudioTagData(
            title=_clean_text(_first(audio.get("title"))),
            artist=_clean_text(_first(audio.get("artist"))),
            album=_clean_text(_first(audio.get("album"))),
            album_artist=_clean_text(_first(audio.get("albumartist"))),
            track_number=_parse_slashed_number(_first(audio.get("tracknumber"))),
            disc_number=_parse_slashed_number(_first(audio.get("discnumber"))),
            genre=_clean_text(_first(audio.get("genre"))),
            composer=_clean_text(_first(audio.get("composer"))),
            publisher=_clean_text(_first(audio.get("label")) or _first(audio.get("publisher"))),
            release_date=_clean_text(_first(audio.get("date"))),
            isrc=_clean_isrc(_first(audio.get("isrc"))),
            upc=_clean_text(_first(audio.get("barcode"))),
            comments=_clean_text(_first(audio.get("comment"))),
            lyrics=_clean_text(_first(audio.get("lyrics"))),
            artwork=artwork,
            raw_fields={"format": "flac"},
        )

    def _write_flac_tags(self, audio: FLAC, tag_data: AudioTagData) -> None:
        def _set(name: str, value):
            if value is None or value == "":
                audio.pop(name, None)
            else:
                audio[name] = [str(value)]

        _set("title", tag_data.title)
        _set("artist", tag_data.artist)
        _set("album", tag_data.album)
        _set("albumartist", tag_data.album_artist)
        _set("tracknumber", tag_data.track_number)
        _set("discnumber", tag_data.disc_number)
        _set("genre", tag_data.genre)
        _set("composer", tag_data.composer)
        _set("label", tag_data.publisher)
        _set("date", tag_data.release_date)
        _set("isrc", normalize_isrc(tag_data.isrc or ""))
        _set("barcode", tag_data.upc)
        _set("comment", tag_data.comments)
        _set("lyrics", tag_data.lyrics)
        audio.clear_pictures()
        if tag_data.artwork is not None:
            picture = Picture()
            picture.data = tag_data.artwork.data
            picture.mime = tag_data.artwork.mime_type or "image/jpeg"
            picture.type = 3
            picture.desc = tag_data.artwork.description or ""
            audio.add_picture(picture)
        audio.save()

    def _read_vorbis_like_tags(self, audio) -> AudioTagData:
        artwork = None
        pictures = getattr(audio, "pictures", None)
        if pictures:
            picture = pictures[0]
            artwork = ArtworkPayload(
                data=bytes(picture.data),
                mime_type=str(picture.mime or "image/jpeg"),
                description=str(picture.desc or ""),
            )
        return AudioTagData(
            title=_clean_text(_first(audio.get("title"))),
            artist=_clean_text(_first(audio.get("artist"))),
            album=_clean_text(_first(audio.get("album"))),
            album_artist=_clean_text(_first(audio.get("albumartist"))),
            track_number=_parse_slashed_number(_first(audio.get("tracknumber"))),
            disc_number=_parse_slashed_number(_first(audio.get("discnumber"))),
            genre=_clean_text(_first(audio.get("genre"))),
            composer=_clean_text(_first(audio.get("composer"))),
            publisher=_clean_text(_first(audio.get("label")) or _first(audio.get("publisher"))),
            release_date=_clean_text(_first(audio.get("date"))),
            isrc=_clean_isrc(_first(audio.get("isrc"))),
            upc=_clean_text(_first(audio.get("barcode"))),
            comments=_clean_text(_first(audio.get("comment"))),
            lyrics=_clean_text(_first(audio.get("lyrics"))),
            artwork=artwork,
            raw_fields={"format": "vorbis"},
        )

    def _write_vorbis_like_tags(self, audio, tag_data: AudioTagData) -> None:
        def _set(name: str, value):
            if value is None or value == "":
                audio.pop(name, None)
            else:
                audio[name] = [str(value)]

        _set("title", tag_data.title)
        _set("artist", tag_data.artist)
        _set("album", tag_data.album)
        _set("albumartist", tag_data.album_artist)
        _set("tracknumber", tag_data.track_number)
        _set("discnumber", tag_data.disc_number)
        _set("genre", tag_data.genre)
        _set("composer", tag_data.composer)
        _set("label", tag_data.publisher)
        _set("date", tag_data.release_date)
        _set("isrc", normalize_isrc(tag_data.isrc or ""))
        _set("barcode", tag_data.upc)
        _set("comment", tag_data.comments)
        _set("lyrics", tag_data.lyrics)
        audio.save()

    def _read_mp4_tags(self, audio: MP4) -> AudioTagData:
        artwork = None
        covers = audio.tags.get("covr", []) if audio.tags else []
        if covers:
            cover = covers[0]
            artwork = ArtworkPayload(
                data=bytes(cover),
                mime_type=(
                    "image/png"
                    if getattr(cover, "imageformat", None) == MP4Cover.FORMAT_PNG
                    else "image/jpeg"
                ),
            )
        return AudioTagData(
            title=_clean_text(_first(audio.tags.get("\xa9nam")) if audio.tags else None),
            artist=_clean_text(_first(audio.tags.get("\xa9ART")) if audio.tags else None),
            album=_clean_text(_first(audio.tags.get("\xa9alb")) if audio.tags else None),
            album_artist=_clean_text(_first(audio.tags.get("aART")) if audio.tags else None),
            track_number=(
                int(_first(audio.tags.get("trkn"))[0])
                if audio.tags and audio.tags.get("trkn")
                else None
            ),
            disc_number=(
                int(_first(audio.tags.get("disk"))[0])
                if audio.tags and audio.tags.get("disk")
                else None
            ),
            genre=_clean_text(_first(audio.tags.get("\xa9gen")) if audio.tags else None),
            composer=_clean_text(_first(audio.tags.get("\xa9wrt")) if audio.tags else None),
            publisher=_clean_text(
                self._decode_mp4_freeform(audio, "LABEL")
                or self._decode_mp4_freeform(audio, "PUBLISHER")
            ),
            release_date=_clean_text(_first(audio.tags.get("\xa9day")) if audio.tags else None),
            isrc=_clean_isrc(self._decode_mp4_freeform(audio, "ISRC")),
            upc=_clean_text(self._decode_mp4_freeform(audio, "UPC")),
            comments=_clean_text(_first(audio.tags.get("\xa9cmt")) if audio.tags else None),
            lyrics=_clean_text(_first(audio.tags.get("\xa9lyr")) if audio.tags else None),
            artwork=artwork,
            raw_fields={"format": "mp4"},
        )

    def _write_mp4_tags(self, audio: MP4, tag_data: AudioTagData) -> None:
        tags = audio.tags or {}

        def _set(name: str, value):
            if value is None or value == "":
                tags.pop(name, None)
            else:
                tags[name] = [value]

        _set("\xa9nam", tag_data.title)
        _set("\xa9ART", tag_data.artist)
        _set("\xa9alb", tag_data.album)
        _set("aART", tag_data.album_artist)
        if tag_data.track_number is None:
            tags.pop("trkn", None)
        else:
            tags["trkn"] = [(int(tag_data.track_number), 0)]
        if tag_data.disc_number is None:
            tags.pop("disk", None)
        else:
            tags["disk"] = [(int(tag_data.disc_number), 0)]
        _set("\xa9gen", tag_data.genre)
        _set("\xa9wrt", tag_data.composer)
        _set("\xa9day", tag_data.release_date)
        _set("\xa9cmt", tag_data.comments)
        _set("\xa9lyr", tag_data.lyrics)
        self._set_mp4_freeform(tags, "LABEL", tag_data.publisher)
        self._set_mp4_freeform(tags, "ISRC", normalize_isrc(tag_data.isrc or ""))
        self._set_mp4_freeform(tags, "UPC", tag_data.upc)
        if tag_data.artwork is None:
            tags.pop("covr", None)
        else:
            image_format = (
                MP4Cover.FORMAT_PNG
                if tag_data.artwork.mime_type == "image/png"
                else MP4Cover.FORMAT_JPEG
            )
            tags["covr"] = [MP4Cover(tag_data.artwork.data, imageformat=image_format)]
        audio.tags = tags
        audio.save()

    @staticmethod
    def _decode_mp4_freeform(audio: MP4, name: str) -> str | None:
        key = f"----:com.apple.iTunes:{name}"
        values = audio.tags.get(key, []) if audio.tags else []
        if not values:
            return None
        value = values[0]
        if isinstance(value, bytes):
            return _clean_text(value.decode("utf-8", "replace"))
        return _clean_text(value)

    @staticmethod
    def _set_mp4_freeform(tags: dict, name: str, value: str | None) -> None:
        key = f"----:com.apple.iTunes:{name}"
        clean = _clean_text(value)
        if not clean:
            tags.pop(key, None)
            return
        tags[key] = [MP4FreeForm(clean.encode("utf-8"))]


class TaggedAudioExportService:
    """Copies managed audio files to an export folder and writes catalog tags to the copies."""

    def __init__(self, tag_service: AudioTagService):
        self.tag_service = tag_service

    def export_copies(
        self,
        *,
        output_dir: str | Path,
        exports: list[tuple[str, str, AudioTagData]],
        progress_callback=None,
        is_cancelled=None,
    ) -> TaggedAudioExportResult:
        destination_root = Path(output_dir)
        destination_root.mkdir(parents=True, exist_ok=True)

        exported = 0
        skipped = 0
        warnings: list[str] = []
        written_paths: list[str] = []

        total = len(exports)
        for index, (source_path, suggested_name, tag_data) in enumerate(exports, start=1):
            if progress_callback is not None:
                progress_callback(
                    index - 1,
                    total,
                    f"Writing tags to exported copy {index} of {total}: {suggested_name}",
                )
            if is_cancelled is not None and is_cancelled():
                raise InterruptedError("Tagged audio export cancelled.")
            source = Path(source_path)
            if not source.exists():
                skipped += 1
                warnings.append(f"Missing source audio: {source}")
                continue
            destination = destination_root / suggested_name
            destination = destination.with_suffix(source.suffix)
            shutil.copy2(source, destination)
            try:
                self.tag_service.write_tags(destination, tag_data)
                exported += 1
                written_paths.append(str(destination))
            except Exception as exc:
                skipped += 1
                warnings.append(f"{destination.name}: {exc}")
                destination.unlink(missing_ok=True)

        if progress_callback is not None:
            progress_callback(total, total, "Tagged audio export finished.")

        return TaggedAudioExportResult(
            requested=len(exports),
            exported=exported,
            skipped=skipped,
            warnings=warnings,
            written_paths=written_paths,
        )
