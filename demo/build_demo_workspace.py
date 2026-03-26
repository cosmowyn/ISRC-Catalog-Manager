from __future__ import annotations

import argparse
import json
import math
import shutil
import sqlite3
import struct
import sys
import wave
import zlib
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QColor, QFont, QImage, QLinearGradient, QPainter, QPen
from PySide6.QtWidgets import QApplication

from isrc_manager.constants import APP_NAME
from isrc_manager.history import HistoryManager
from isrc_manager.parties import PartyService
from isrc_manager.services import (
    CatalogAdminService,
    CustomFieldDefinitionService,
    CustomFieldValueService,
    DatabaseSchemaService,
    LicenseService,
    ProfileKVService,
    SettingsMutationService,
    TrackCreatePayload,
    TrackService,
)
from isrc_manager.services.import_governance import GovernedImportCoordinator
from isrc_manager.works import WorkService


@dataclass(frozen=True, slots=True)
class DemoTrack:
    isrc: str
    title: str
    artist: str
    additional_artists: tuple[str, ...]
    album: str
    release_date: str
    length_seconds: int
    iswc: str
    upc: str
    genre: str
    catalog_number: str
    buma_work_number: str
    audio_asset: str
    art_asset: str
    distribution_status: str
    mastered: bool
    mood: str
    buy_url: str
    notes: str


DEMO_TRACKS: tuple[DemoTrack, ...] = (
    DemoTrack(
        "ZZ-DMO-26-00001",
        "Aurora Signal",
        "Northwind Atlas",
        ("Vela Harbor",),
        "Luminous Cartography",
        "2026-01-12",
        263,
        "T-100.200.300-1",
        "123456789012",
        "Ambient Electronica",
        "NW-001",
        "BUMA-41001",
        "aurora-signal.wav",
        "luminous-cartography.png",
        "Released",
        True,
        "Cinematic",
        "https://demo.example/aurora-signal",
        "Lead single for the fictional Northwind Atlas campaign.",
    ),
    DemoTrack(
        "ZZ-DMO-26-00002",
        "Static Bloom",
        "Northwind Atlas",
        ("June Meridian",),
        "Luminous Cartography",
        "2026-01-12",
        219,
        "T-100.200.300-2",
        "123456789012",
        "Ambient Electronica",
        "NW-002",
        "BUMA-41002",
        "static-bloom.wav",
        "luminous-cartography.png",
        "Released",
        True,
        "Reflective",
        "https://demo.example/static-bloom",
        "Uses a softer palette to show contrasting waveform lengths.",
    ),
    DemoTrack(
        "ZZ-DMO-26-00003",
        "Glass Horizon",
        "Northwind Atlas",
        tuple(),
        "Luminous Cartography",
        "2026-01-12",
        301,
        "T-100.200.300-3",
        "123456789012",
        "Ambient Electronica",
        "NW-003",
        "BUMA-41003",
        "glass-horizon.wav",
        "luminous-cartography.png",
        "Released",
        True,
        "Expansive",
        "https://demo.example/glass-horizon",
        "Album centerpiece used in the workspace screenshot.",
    ),
    DemoTrack(
        "ZZ-DMO-26-00004",
        "Night Transit",
        "Paper Moons",
        ("Northwind Atlas",),
        "City of Quiet Motion",
        "2026-02-07",
        247,
        "T-100.200.300-4",
        "123456789013",
        "Indie Electronic",
        "PM-001",
        "BUMA-42001",
        "night-transit.wav",
        "city-of-quiet-motion.png",
        "Scheduled",
        True,
        "Driving",
        "https://demo.example/night-transit",
        "Demonstrates multiple artists and a second album grouping.",
    ),
    DemoTrack(
        "ZZ-DMO-26-00005",
        "Paper Lantern Run",
        "Paper Moons",
        tuple(),
        "City of Quiet Motion",
        "2026-02-07",
        234,
        "T-100.200.300-5",
        "123456789013",
        "Indie Electronic",
        "PM-002",
        "BUMA-42002",
        "paper-lantern-run.wav",
        "city-of-quiet-motion.png",
        "Scheduled",
        False,
        "Uplifting",
        "https://demo.example/paper-lantern-run",
        "Still awaiting final mastering in the fictional release flow.",
    ),
    DemoTrack(
        "ZZ-DMO-26-00006",
        "Velvet Switchboard",
        "Paper Moons",
        ("June Meridian",),
        "City of Quiet Motion",
        "2026-02-07",
        286,
        "T-100.200.300-6",
        "123456789013",
        "Indie Electronic",
        "PM-003",
        "BUMA-42003",
        "velvet-switchboard.wav",
        "city-of-quiet-motion.png",
        "Scheduled",
        True,
        "Night Drive",
        "https://demo.example/velvet-switchboard",
        "Useful row for screenshots because of the longer title length.",
    ),
    DemoTrack(
        "ZZ-DMO-26-00007",
        "Signal Garden",
        "June Meridian",
        tuple(),
        "Satellite Letters",
        "2026-03-21",
        205,
        "T-100.200.300-7",
        "123456789014",
        "Dream Pop",
        "JM-001",
        "BUMA-43001",
        "signal-garden.wav",
        "satellite-letters.png",
        "Draft",
        False,
        "Dreamy",
        "https://demo.example/signal-garden",
        "Draft row kept to demonstrate lifecycle columns in custom metadata.",
    ),
    DemoTrack(
        "ZZ-DMO-26-00008",
        "Moonwire Postcard",
        "June Meridian",
        ("Paper Moons",),
        "Satellite Letters",
        "2026-03-21",
        256,
        "T-100.200.300-8",
        "123456789014",
        "Dream Pop",
        "JM-002",
        "BUMA-43002",
        "moonwire-postcard.wav",
        "satellite-letters.png",
        "Draft",
        False,
        "Lush",
        "https://demo.example/moonwire-postcard",
        "Cross-feature row for a fictional collaboration.",
    ),
)


CUSTOM_FIELD_DEFINITIONS = [
    {
        "id": None,
        "name": "Distribution Status",
        "field_type": "dropdown",
        "options": json.dumps(["Draft", "Scheduled", "Released"]),
    },
    {"id": None, "name": "Mastered", "field_type": "checkbox", "options": None},
    {"id": None, "name": "Notes", "field_type": "text", "options": None},
    {"id": None, "name": "Buy URL", "field_type": "text", "options": None},
    {
        "id": None,
        "name": "Mood",
        "field_type": "dropdown",
        "options": json.dumps(
            [
                "Cinematic",
                "Reflective",
                "Driving",
                "Dreamy",
                "Lush",
                "Expansive",
                "Uplifting",
                "Night Drive",
            ]
        ),
    },
]


def _png_chunk(tag: bytes, data: bytes) -> bytes:
    return (
        struct.pack(">I", len(data))
        + tag
        + data
        + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    )


def _write_png(
    path: Path,
    *,
    width: int = 1400,
    height: int = 1400,
    title: str,
    subtitle: str,
    start: str,
    end: str,
) -> None:
    image = QImage(width, height, QImage.Format_ARGB32)
    image.fill(QColor("#0f172a"))

    painter = QPainter(image)
    painter.setRenderHint(QPainter.Antialiasing, True)

    gradient = QLinearGradient(0, 0, width, height)
    gradient.setColorAt(0.0, QColor(start))
    gradient.setColorAt(1.0, QColor(end))
    painter.fillRect(image.rect(), gradient)

    painter.setPen(QPen(QColor(255, 255, 255, 28), 2))
    step = max(72, width // 16)
    for x in range(-height, width, step):
        painter.drawLine(x, 0, x + height, height)

    painter.setPen(QColor("#F8FAFC"))
    title_font = QFont("Helvetica Neue", 74)
    title_font.setBold(True)
    painter.setFont(title_font)
    painter.drawText(96, 240, title)

    painter.setPen(QColor("#E2E8F0"))
    subtitle_font = QFont("Helvetica Neue", 28)
    painter.setFont(subtitle_font)
    painter.drawText(100, 308, subtitle)

    badge_rects = [
        (96, height - 300, 280, 112, "DEMO"),
        (404, height - 300, 360, 112, "FICTIONAL DATA"),
    ]
    for x, y, w, h, text in badge_rects:
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(255, 255, 255, 36))
        painter.drawRoundedRect(x, y, w, h, 22, 22)
        painter.setPen(QColor("#F8FAFC"))
        badge_font = QFont("Helvetica Neue", 24)
        badge_font.setBold(True)
        painter.setFont(badge_font)
        painter.drawText(x + 28, y + 70, text)

    painter.end()
    image.save(str(path))


def _write_tone(path: Path, *, seconds: int, frequency: float) -> None:
    sample_rate = 44100
    amplitude = 16000
    total_frames = seconds * sample_rate
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        frames = bytearray()
        for idx in range(total_frames):
            sample = int(amplitude * math.sin((2.0 * math.pi * frequency * idx) / sample_rate))
            frames.extend(struct.pack("<h", sample))
        wav_file.writeframes(bytes(frames))


def _write_pdf(path: Path, *, title: str, body_lines: list[str]) -> None:
    lines = [title, *body_lines]
    escaped = []
    for line in lines:
        escaped_line = line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        escaped.append(f"({escaped_line}) Tj")
    text_block = "BT /F1 18 Tf 72 740 Td " + " 0 -28 Td ".join(escaped) + " ET"
    content = text_block.encode("latin-1")
    pdf_bytes = (
        b"%PDF-1.4\n"
        b"1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj\n"
        b"2 0 obj << /Type /Pages /Kids [3 0 R] /Count 1 >> endobj\n"
        b"3 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >> endobj\n"
        b"4 0 obj << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> endobj\n"
        + f"5 0 obj << /Length {len(content)} >> stream\n".encode("ascii")
        + content
        + b"\nendstream endobj\nxref\n0 6\n0000000000 65535 f \n"
        b"0000000010 00000 n \n0000000063 00000 n \n0000000122 00000 n \n"
        b"0000000248 00000 n \n0000000318 00000 n \n"
        b"trailer << /Size 6 /Root 1 0 R >>\nstartxref\n"
        b"0\n%%EOF\n"
    )
    path.write_bytes(pdf_bytes)


def _ensure_dirs(base_dir: Path) -> tuple[Path, Path]:
    data_root = base_dir / APP_NAME
    asset_root = base_dir / "source_assets"
    if data_root.exists():
        shutil.rmtree(data_root)
    asset_root.mkdir(parents=True, exist_ok=True)
    for rel in ("Database", "track_media", "licenses", "history", "exports", "logs", "backups"):
        (data_root / rel).mkdir(parents=True, exist_ok=True)
    for rel in ("audio", "images", "licenses"):
        (asset_root / rel).mkdir(parents=True, exist_ok=True)
    return data_root, asset_root


def build_demo_workspace(base_dir: Path) -> dict[str, Path]:
    base_dir = Path(base_dir).resolve()
    _app = QApplication.instance() or QApplication([])
    data_root, asset_root = _ensure_dirs(base_dir)
    db_path = data_root / "Database" / "demo_showcase.db"

    album_art_specs = {
        "luminous-cartography.png": (
            "Luminous Cartography",
            "Fictional ambient-electronica release",
            "#1d4ed8",
            "#0f766e",
        ),
        "city-of-quiet-motion.png": (
            "City of Quiet Motion",
            "Fictional indie-electronic release",
            "#b45309",
            "#7c2d12",
        ),
        "satellite-letters.png": (
            "Satellite Letters",
            "Fictional dream-pop release",
            "#9333ea",
            "#0f766e",
        ),
    }
    for filename, (title, subtitle, start, end) in album_art_specs.items():
        _write_png(
            asset_root / "images" / filename, title=title, subtitle=subtitle, start=start, end=end
        )

    tone_specs = {
        "aurora-signal.wav": (4, 246.94),
        "static-bloom.wav": (4, 261.63),
        "glass-horizon.wav": (5, 293.66),
        "night-transit.wav": (4, 329.63),
        "paper-lantern-run.wav": (4, 349.23),
        "velvet-switchboard.wav": (5, 392.00),
        "signal-garden.wav": (3, 440.00),
        "moonwire-postcard.wav": (4, 493.88),
    }
    for filename, (seconds, frequency) in tone_specs.items():
        _write_tone(asset_root / "audio" / filename, seconds=seconds, frequency=frequency)

    license_specs = {
        "northwind_sync_license.pdf": [
            "Northwind Atlas",
            "Sync License",
            "Demo-only paperwork for repository screenshots.",
        ],
        "paper_moons_live_license.pdf": [
            "Paper Moons",
            "Live Recording License",
            "Fictional agreement for a showcase release.",
        ],
        "june_meridian_artwork_clearance.pdf": [
            "June Meridian",
            "Artwork Clearance",
            "Fictional supporting document for the demo catalog.",
        ],
    }
    for filename, lines in license_specs.items():
        _write_pdf(asset_root / "licenses" / filename, title=lines[0], body_lines=lines[1:])

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")

    schema = DatabaseSchemaService(conn, data_root=data_root)
    schema.init_db()
    schema.migrate_schema()

    track_service = TrackService(conn, data_root, require_governed_creation=True)
    custom_defs = CustomFieldDefinitionService(conn)
    custom_values = CustomFieldValueService(conn, custom_defs, data_root)
    license_service = LicenseService(conn, data_root)
    catalog_admin = CatalogAdminService(conn)
    profile_kv = ProfileKVService(conn)
    party_service = PartyService(conn)
    work_service = WorkService(conn, party_service=party_service)
    governed_tracks = GovernedImportCoordinator(
        conn,
        track_service=track_service,
        party_service=party_service,
        work_service=work_service,
        profile_name=db_path.name,
    )
    profile_kv.ensure_store()

    with conn:
        conn.execute("DELETE FROM ISRC_Prefix")
        conn.execute("INSERT INTO ISRC_Prefix(id, prefix) VALUES (1, ?)", ("ZZDMO",))
        conn.execute("DELETE FROM SENA")
        conn.execute("INSERT INTO SENA(id, number) VALUES (1, ?)", ("DEMO-SENA-001",))
        conn.execute("DELETE FROM BTW")
        conn.execute("INSERT INTO BTW(id, nr) VALUES (1, ?)", ("DEMO-BTW-001",))
        conn.execute("DELETE FROM BUMA_STEMRA")
        conn.execute(
            "INSERT INTO BUMA_STEMRA(id, relatie_nummer, ipi) VALUES (1, ?, ?)",
            ("DEMO-BUMA-001", "IPI-DEMO-0001"),
        )

    settings_ini = base_dir / "demo_settings.ini"
    qsettings = QSettings(str(settings_ini), QSettings.IniFormat)
    qsettings.setFallbacksEnabled(False)
    qsettings.setValue("ui/window_title", "ISRC Catalog Manager Demo")
    qsettings.setValue("ui/icon_path", "")

    settings_mutations = SettingsMutationService(conn, qsettings)
    settings_mutations.set_identity(window_title="ISRC Catalog Manager Demo", icon_path="")
    settings_mutations.set_auto_snapshot_enabled(True)
    settings_mutations.set_auto_snapshot_interval_minutes(30)

    custom_defs.sync_fields([], CUSTOM_FIELD_DEFINITIONS)
    active_custom_fields = custom_defs.list_active_fields()
    field_ids = {field["name"]: int(field["id"]) for field in active_custom_fields}

    history = HistoryManager(conn, qsettings, db_path, data_root / "history", data_root)

    track_ids: list[int] = []
    for track in DEMO_TRACKS:
        payload = TrackCreatePayload(
            isrc=track.isrc,
            track_title=track.title,
            artist_name=track.artist,
            additional_artists=list(track.additional_artists),
            album_title=track.album,
            release_date=track.release_date,
            track_length_sec=track.length_seconds,
            iswc=track.iswc,
            upc=track.upc,
            genre=track.genre,
            catalog_number=track.catalog_number,
            buma_work_number=track.buma_work_number,
            audio_file_source_path=str(asset_root / "audio" / track.audio_asset),
            album_art_source_path=str(asset_root / "images" / track.art_asset),
        )
        track_id = governed_tracks.create_governed_track(
            payload,
            governance_mode="create_new_work",
            profile_name=db_path.name,
        ).track_id
        track_ids.append(track_id)
        history.record_track_create(
            track_id=track_id, cleanup_artist_names=[], cleanup_album_titles=[]
        )
        custom_values.save_value(
            track_id, field_ids["Distribution Status"], value=track.distribution_status
        )
        custom_values.save_value(
            track_id, field_ids["Mastered"], value="1" if track.mastered else "0"
        )
        custom_values.save_value(track_id, field_ids["Mood"], value=track.mood)
        custom_values.save_value(track_id, field_ids["Buy URL"], value=track.buy_url)
        custom_values.save_value(track_id, field_ids["Notes"], value=track.notes)

    catalog_admin.ensure_licensee("Aster House Licensing")
    catalog_admin.ensure_licensee("Harbor Rights Collective")
    catalog_admin.ensure_licensee("Velvet Window Music")

    license_service.add_license(
        track_id=track_ids[0],
        licensee_name="Aster House Licensing",
        source_pdf_path=asset_root / "licenses" / "northwind_sync_license.pdf",
    )
    license_service.add_license(
        track_id=track_ids[3],
        licensee_name="Harbor Rights Collective",
        source_pdf_path=asset_root / "licenses" / "paper_moons_live_license.pdf",
    )
    license_service.add_license(
        track_id=track_ids[6],
        licensee_name="Velvet Window Music",
        source_pdf_path=asset_root / "licenses" / "june_meridian_artwork_clearance.pdf",
    )

    history.record_event(
        label="Demo licenses seeded",
        action_type="demo.licenses_seeded",
        entity_type="License",
        entity_id="batch",
        payload={"count": 3},
    )
    history.create_manual_snapshot("Demo seed complete")
    history.create_manual_snapshot("Metadata showcase ready")

    conn.close()
    qsettings.sync()

    return {
        "base_dir": base_dir,
        "data_root": data_root,
        "db_path": db_path,
        "settings_ini": settings_ini,
        "asset_root": asset_root,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build a fictional demo workspace for ISRC Catalog Manager."
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "demo" / ".runtime",
        help="Base folder where the demo LOCALAPPDATA-style tree should be created.",
    )
    args = parser.parse_args()

    info = build_demo_workspace(args.output)
    print(f"Demo workspace created at: {info['data_root']}")
    print(f"Demo database: {info['db_path']}")
    print(f"Demo settings: {info['settings_ini']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
