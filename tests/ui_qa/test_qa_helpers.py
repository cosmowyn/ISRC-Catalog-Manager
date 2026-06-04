import builtins
import sqlite3
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest
from PySide6.QtGui import QAction, QColor, QImage, QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QSpinBox,
    QTableView,
    QTableWidget,
    QTableWidgetItem,
    QWidget,
)

from isrc_manager.code_registry import CodeRegistryService
from isrc_manager.help_content import (
    iter_help_chapter_screenshot_references,
)
from isrc_manager.qa import assertions, commands, fixtures, scenarios
from isrc_manager.qa.deviations import DeviationRecorder
from isrc_manager.qa.evidence import EvidenceRecorder
from isrc_manager.qa.help_validation import validate_help_coverage
from isrc_manager.qa.inventory import UIInventoryItem
from isrc_manager.qa.traceability import (
    TraceabilityEntry,
    build_traceability_matrix,
    write_traceability_matrix,
)
from isrc_manager.qa.visual import (
    VisualQualificationService,
    _capture_from_image_file,
    _compare_image_files,
    _escape_html,
    _normalize_text,
    _safe_name,
)
from isrc_manager.services import DatabaseSchemaService


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _connection() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA foreign_keys = ON")
    schema = DatabaseSchemaService(conn)
    schema.init_db()
    schema.migrate_schema()
    CodeRegistryService(conn)
    return conn


class _Evidence:
    def __init__(self) -> None:
        self.records: list[tuple[str, str, str, dict[str, object]]] = []

    def record(self, test_id: str, *, status: str, message: str, data: dict[str, object]) -> None:
        self.records.append((test_id, status, message, data))


class _Harness:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.connection = conn
        self.database_path = ":memory:"
        self.evidence = _Evidence()
        self.inventory: list[object] = []

    def process_events(self, *, cycles: int = 1) -> None:
        for _ in range(cycles):
            _app().processEvents()


def test_command_helpers_find_trigger_and_scan_table_text() -> None:
    _app()
    window = QMainWindow()
    action = QAction("&Report a Bug", window)
    action.setObjectName("reportBugAction")
    action.setToolTip("Manual bug report")
    window.addAction(action)
    triggered: list[bool] = []
    action.triggered.connect(lambda: triggered.append(True))

    assert commands.action_label(action) == "Report a Bug"
    assert commands.find_action(window, "reportBugAction") is action
    assert commands.find_action(window, "Manual bug report") is action
    assert commands.safe_trigger_action(window, "Report a Bug")
    assert triggered == [True]

    action.setEnabled(False)
    assert not commands.safe_trigger_action(window, "Report a Bug")
    assert commands.find_action(window, "missing") is None

    table = QTableWidget(2, 2)
    table.setItem(0, 0, QTableWidgetItem("Alpha"))
    table.setItem(1, 1, QTableWidgetItem("Needle"))
    assert commands.table_contains_text(table, "Needle")
    assert not commands.table_contains_text(table, "Missing")

    model = QStandardItemModel()
    model.setItem(0, 0, QStandardItem("Model needle"))
    view = QTableView()
    view.setModel(model)
    assert commands.table_contains_text(view, "needle")

    empty_view = QTableView()
    assert not commands.table_contains_text(empty_view, "anything")


def test_assertion_helpers_report_missing_artifacts_inventory_and_evidence(tmp_path: Path) -> None:
    artifact = tmp_path / "artifact.txt"
    with pytest.raises(AssertionError, match="does not exist"):
        assertions.require_artifact(artifact)
    artifact.write_text("", encoding="utf-8")
    with pytest.raises(AssertionError, match="empty"):
        assertions.require_artifact(artifact)
    artifact.write_text("ok", encoding="utf-8")
    assert assertions.require_artifact(artifact) == artifact

    item = UIInventoryItem(
        inventory_id="help.action",
        kind="action",
        ui_area="settings_theme_help",
        object_name="helpAction",
        text="Help",
        class_name="QAction",
        parent="menu",
        path="menu/help",
        visible=True,
        enabled=True,
        has_stable_object_name=True,
    )
    assertions.require_inventory_area([item], "settings_theme_help")
    with pytest.raises(AssertionError, match="catalog"):
        assertions.require_inventory_area([item], "catalog")

    event = SimpleNamespace(test_id="UI-PQ-001", status="passed")
    assertions.require_evidence_status([event], "UI-PQ-001")
    with pytest.raises(AssertionError, match="UI-PQ-002"):
        assertions.require_evidence_status([event], "UI-PQ-002")


def test_pq_artifact_recorders_write_deviations_evidence_and_traceability(tmp_path: Path) -> None:
    deviations = DeviationRecorder(tmp_path / "deviations.csv")
    explicit = deviations.add(
        test_id="UI-PQ-X",
        severity="medium",
        ui_area="catalog",
        workflow="Catalog",
        ui_object="button.add",
        step="Click",
        expected="Track created",
        actual="Track missing",
        database_path="qa.db",
        evidence_path="evidence.json",
        coverage_status="failed",
    )
    assert explicit.deviation_id == "UI-PQ-DEV-0001"
    try:
        raise RuntimeError("boom")
    except RuntimeError as exc:
        recorded = deviations.record_exception(
            test_id="UI-PQ-ERR",
            ui_area="settings_theme_help",
            workflow="Help",
            ui_object="help.dialog",
            step="Open",
            expected="Dialog opens",
            exc=exc,
            screenshot_path="help.png",
        )
    assert recorded.exception_type == "RuntimeError"
    deviation_path = deviations.write()
    assert "UI-PQ-DEV-0002" in deviation_path.read_text(encoding="utf-8")

    evidence = EvidenceRecorder(tmp_path / "evidence")
    event = evidence.record(
        "UI-PQ-X",
        status="passed",
        message="Workflow verified",
        data={"rows": 2},
    )
    assert event.data == {"rows": 2}
    assert '"rows": 2' in evidence.write_json().read_text(encoding="utf-8")
    summary = evidence.write_summary(
        inventory_count=3,
        traceability_count=2,
        deviation_count=len(deviations.deviations),
        automated_count=1,
        pending_count=1,
        database_path="qa.db",
        open_deviation_count=1,
        pending_deviation_count=1,
        object_name_gap_count=1,
    )
    assert "UI-PQ-X" in summary.read_text(encoding="utf-8")

    uncovered = UIInventoryItem(
        inventory_id="unknown.button",
        kind="button",
        ui_area="unknown_area",
        object_name="",
        text="Mystery",
        class_name="QPushButton",
        parent="window",
        path="window/Mystery",
        visible=True,
        enabled=True,
        has_stable_object_name=False,
    )
    pending = UIInventoryItem(
        inventory_id="media.field",
        kind="field",
        ui_area="media_audio",
        object_name="",
        text="Media Field",
        class_name="QLineEdit",
        parent="window",
        path="window/Media Field",
        visible=True,
        enabled=True,
        has_stable_object_name=False,
    )
    secondary = UIInventoryItem(
        inventory_id="search.action",
        kind="action",
        ui_area="search",
        object_name="searchAction",
        text="Search",
        class_name="QAction",
        parent="menu",
        path="menu/Search",
        visible=True,
        enabled=True,
        has_stable_object_name=True,
    )
    rows = build_traceability_matrix(
        [uncovered, pending, secondary],
        deviations=deviations,
        entries=[
            TraceabilityEntry(
                "UI-PQ-MEDIA-001",
                "media_audio",
                "Media workflow",
                "media controls",
                "Functional Qualification",
                "pending",
                "QA profile",
                "Synthetic media",
                "Inspect media controls",
                "Controls are traceable",
                "Media records",
                "Codec fixtures",
                "evidence.json",
                "Missing media traceability",
                manual_followup_status="media fixtures pending",
            ),
            TraceabilityEntry(
                "UI-PQ-MISC-001",
                "assets_deliverables",
                "Secondary surfaces",
                "secondary controls",
                "Inventory Qualification",
                "automated",
                "QA profile",
                "Runtime inventory",
                "Map secondary controls",
                "Controls are covered",
                "Secondary records",
                "Feature services",
                "traceability_matrix.csv",
                "Missing secondary traceability",
            ),
        ],
        database_path="qa.db",
        evidence_path="evidence.json",
    )
    assert [row.coverage_status for row in rows] == [
        "uncovered",
        "pending_manual",
        "covered",
    ]
    trace_path = write_traceability_matrix(tmp_path / "traceability.csv", rows)
    trace_text = trace_path.read_text(encoding="utf-8")
    assert "unknown.button" in trace_text
    assert "\r" not in trace_text
    assert any(item.coverage_status == "object_name_gap" for item in deviations.deviations)


def test_fixture_helpers_create_full_repertoire_records() -> None:
    conn = _connection()

    track_id = fixtures.create_qa_track(conn)
    ids = fixtures.create_qa_repertoire(conn, track_id=track_id)

    assert ids.track_id == track_id
    assert (
        conn.execute("SELECT COUNT(*) FROM Tracks WHERE id=?", (ids.track_id,)).fetchone()[0] == 1
    )
    assert (
        conn.execute("SELECT COUNT(*) FROM Parties WHERE id=?", (ids.party_id,)).fetchone()[0] == 1
    )
    assert conn.execute("SELECT COUNT(*) FROM Works WHERE id=?", (ids.work_id,)).fetchone()[0] == 1
    assert (
        conn.execute("SELECT COUNT(*) FROM Releases WHERE id=?", (ids.release_id,)).fetchone()[0]
        == 1
    )
    assert (
        conn.execute("SELECT COUNT(*) FROM Contracts WHERE id=?", (ids.contract_id,)).fetchone()[0]
        == 1
    )
    assert (
        conn.execute("SELECT COUNT(*) FROM RightsRecords WHERE id=?", (ids.right_id,)).fetchone()[0]
        == 1
    )

    conn.close()


def test_scenario_low_level_helpers_cover_success_and_error_edges(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _app()
    conn = _connection()
    harness = _Harness(conn)

    combo = QComboBox()
    combo.setEditable(True)
    combo.addItems(["One", "Two"])
    scenarios._set_combo_text(combo, "Typed")
    assert combo.currentText() == "Typed"
    combo.addItem("Payload", 42)
    scenarios._set_combo_by_data(combo, 42)
    assert combo.currentData() == 42
    scenarios._set_combo_by_data(object(), 42)

    class _ComboLike:
        def __init__(self) -> None:
            self.current = ""
            self.edited = ""

        def setCurrentText(self, value: str) -> None:
            self.current = value

        def setEditText(self, value: str) -> None:
            self.edited = value

    combo_like = _ComboLike()
    scenarios._set_combo_text(combo_like, "Other")
    assert combo_like.current == "Other"
    assert combo_like.edited == "Other"
    current_only = SimpleNamespace(current="")
    current_only.setCurrentText = lambda value: setattr(current_only, "current", value)
    scenarios._set_combo_text(current_only, "Current only")
    assert current_only.current == "Current only"

    line_like = SimpleNamespace(text="", setText=lambda value: setattr(line_like, "text", value))
    scenarios._set_combo_text(line_like, "Text")
    assert line_like.text == "Text"
    scenarios._set_combo_text(object(), "ignored")
    scenarios._set_combo_by_data(combo, "missing")

    conn.execute("CREATE TABLE qa_probe(id INTEGER PRIMARY KEY, label TEXT)")
    conn.execute("INSERT INTO qa_probe(label) VALUES ('ready')")
    assert (
        scenarios._wait_for_row(
            harness,
            "SELECT id, label FROM qa_probe WHERE label=?",
            ("ready",),
            label="probe",
        )[1]
        == "ready"
    )
    with pytest.raises(AssertionError, match="missing was not persisted"):
        scenarios._wait_for_row(
            harness,
            "SELECT id FROM qa_probe WHERE label=?",
            ("missing",),
            label="missing",
        )
    assert (
        scenarios._try_wait_for_row(
            harness,
            "SELECT id FROM qa_probe WHERE label=?",
            ("missing",),
            attempts=1,
        )
        is None
    )
    fake_button = SimpleNamespace(
        text=lambda: "Create Work + Save Track",
        isEnabled=lambda: False,
    )
    fake_window = SimpleNamespace(
        save_button=fake_button,
        _current_work_track_context=lambda: {"mode": "create_new_work"},
    )
    failure_context = scenarios._catalog_track_persistence_failure_context(fake_window)
    assert "Create Work + Save Track" in failure_context
    assert "save_button_enabled=False" in failure_context
    assert "create_new_work" in failure_context

    table = QTableWidget(3, 1)
    table.setItem(0, 0, QTableWidgetItem("not-int"))
    table.setItem(1, 0, QTableWidgetItem("7"))
    assert scenarios._table_has_id(table, 7)
    assert not scenarios._table_has_id(table, 8)

    button = QPushButton("&Run")
    root = QMainWindow()
    button.setParent(root)
    button.show()
    clicked: list[bool] = []
    button.clicked.connect(lambda: clicked.append(True))
    assert scenarios._click_button(root, "Run") is button
    assert clicked == [True]
    button.setEnabled(False)
    with pytest.raises(AssertionError, match="Enabled button"):
        scenarios._click_button(root, "Run")

    assert scenarios._single_int(conn, "SELECT 5") == 5
    assert scenarios._single_int(conn, "SELECT id FROM qa_probe WHERE label='not-there'") == 0
    assert scenarios._single_int(conn, "SELECT COUNT(*) FROM qa_probe WHERE label='x'") == 0

    real_import = builtins.__import__

    def _raise_for_optional_audio_packages(name, *args, **kwargs):
        if name in {"numpy", "soundfile"}:
            raise ImportError(name)
        return real_import(name, *args, **kwargs)

    with monkeypatch.context() as import_patch:
        import_patch.setattr(builtins, "__import__", _raise_for_optional_audio_packages)
        fallback_wav = scenarios._write_synthetic_wav_fixture(
            tmp_path / "fallback.wav",
            duration_seconds=0,
            seed=11,
        )
    assert fallback_wav.exists()
    assert fallback_wav.stat().st_size > 44

    converter = scenarios._QAAudioConversionService()
    source = tmp_path / "source.wav"
    destination = tmp_path / "converted" / "copy.mp3"
    source.write_bytes(b"audio")
    result = converter.transcode(
        source_path=source,
        destination_path=destination,
        target_id="MP3",
        metadata_behavior="strip",
    )
    assert converter.is_available()
    assert converter.is_supported_target("mp3", capability_group="managed_lossy")
    assert not converter.is_supported_target("wav", capability_group="managed_lossy")
    assert converter.is_supported_target("wav", capability_group="managed_forensic")
    assert not converter.is_supported_target("mp3", capability_group="managed_forensic")
    assert converter.is_supported_target("wav", capability_group="managed")
    assert not converter.is_supported_target("flac", capability_group="managed_any")
    assert converter.is_supported_target("mp3")
    assert result.destination_path == destination
    assert destination.read_bytes() == b"audio"
    assert converter.calls[-1]["metadata_behavior"] == "strip"

    class _TrackService:
        def __init__(self, *, persisted: bool = True) -> None:
            self.persisted = persisted

        def set_media_path(self, track_id, media_key, path, *, storage_mode, progress_callback):
            progress_callback(1, 1, f"{track_id}:{media_key}:{storage_mode}")
            assert Path(path).exists()
            return {"path": str(path)}

        def has_media(self, _track_id, _media_key):
            return self.persisted

    def _write_stub_wav(path, **_kwargs):
        clean_path = Path(path)
        clean_path.parent.mkdir(parents=True, exist_ok=True)
        clean_path.write_bytes(b"wav")
        return clean_path

    monkeypatch.setattr(scenarios, "_write_synthetic_wav_fixture", _write_stub_wav)
    media_harness = SimpleNamespace(
        window=SimpleNamespace(track_service=_TrackService()),
        artifact_dir=tmp_path,
        connection=SimpleNamespace(commit=mock.Mock()),
    )
    fixture_path, meta, messages = scenarios._attach_synthetic_audio_to_track(
        media_harness,
        track_id=7,
        stem="attached",
        duration_seconds=1,
        seed=3,
    )
    assert fixture_path.read_bytes() == b"wav"
    assert meta["path"] == str(fixture_path)
    assert messages == ["7:audio_file:managed_file"]
    media_harness.connection.commit.assert_called_once()
    with pytest.raises(AssertionError, match="Track service is required"):
        scenarios._attach_synthetic_audio_to_track(
            SimpleNamespace(window=None, artifact_dir=tmp_path),
            track_id=1,
            stem="missing",
            duration_seconds=1,
            seed=1,
        )
    with pytest.raises(AssertionError, match="not persisted"):
        scenarios._attach_synthetic_audio_to_track(
            SimpleNamespace(
                window=SimpleNamespace(track_service=_TrackService(persisted=False)),
                artifact_dir=tmp_path,
                connection=SimpleNamespace(commit=mock.Mock()),
            ),
            track_id=8,
            stem="unpersisted",
            duration_seconds=1,
            seed=4,
        )

    artifact_harness = SimpleNamespace(artifact_dir=tmp_path)
    stale_dir = scenarios._reset_generated_artifact_dir(artifact_harness, "stale")
    (stale_dir / "old.txt").write_text("old", encoding="utf-8")
    reset_dir = scenarios._reset_generated_artifact_dir(artifact_harness, "stale")
    assert reset_dir.is_dir()
    assert not (reset_dir / "old.txt").exists()
    stale_file = tmp_path / "single-artifact"
    stale_file.write_text("old", encoding="utf-8")
    assert scenarios._reset_generated_artifact_dir(artifact_harness, "single-artifact").is_dir()
    with pytest.raises(AssertionError, match="outside"):
        scenarios._reset_generated_artifact_dir(artifact_harness, "../outside")

    visual_service = VisualQualificationService(
        tmp_path,
        manifest_name="business_workflow_manifest.json",
    )
    visual_harness = SimpleNamespace(
        artifact_dir=tmp_path,
        _business_workflow_visual_service=visual_service,
    )
    assert scenarios._workflow_visual_service(visual_harness) is visual_service
    new_visual_harness = SimpleNamespace(artifact_dir=tmp_path)
    assert scenarios._workflow_visual_service(new_visual_harness).manifest_path.name == (
        "business_workflow_manifest.json"
    )

    capture_calls: list[str] = []
    monkeypatch.setattr(
        scenarios,
        "_capture_help_surface",
        lambda *_args, **_kwargs: capture_calls.append("capture"),
    )
    dialog = QDialog()
    dialog.close = lambda: capture_calls.append("close")
    dialog.deleteLater = lambda: capture_calls.append("delete")
    help_harness = SimpleNamespace(process_events=lambda **_kwargs: capture_calls.append("events"))
    scenarios._capture_help_dialog_surface(
        help_harness,
        mock.Mock(),
        tmp_path,
        dialog,
        "help-dialog",
        [],
    )
    assert capture_calls == ["capture", "close", "delete", "events"]

    with pytest.raises(AssertionError, match="open application window"):
        scenarios._ensure_help_visual_track(SimpleNamespace(window=None))
    missing_services_conn = sqlite3.connect(":memory:")
    missing_services_conn.execute("CREATE TABLE Tracks(id INTEGER PRIMARY KEY, track_title TEXT)")
    with pytest.raises(AssertionError, match="Track and Work services"):
        scenarios._ensure_help_visual_track(
            SimpleNamespace(
                window=SimpleNamespace(track_service=None, work_service=None),
                connection=missing_services_conn,
            )
        )
    missing_services_conn.close()
    help_conn = sqlite3.connect(":memory:")
    help_conn.execute("CREATE TABLE Tracks(id INTEGER PRIMARY KEY, track_title TEXT)")
    help_conn.execute(
        "INSERT INTO Tracks(id, track_title) VALUES(42, 'Help Screenshot Reference Track')"
    )
    assert (
        scenarios._ensure_help_visual_track(SimpleNamespace(window=object(), connection=help_conn))
        == 42
    )
    help_conn.close()
    help_create_conn = sqlite3.connect(":memory:")
    help_create_conn.execute("CREATE TABLE Tracks(id INTEGER PRIMARY KEY, track_title TEXT)")
    refresh_calls: list[dict[str, object]] = []

    class _HelpWorkService:
        def create_work(self, payload):
            assert payload.title == "Help Screenshot Reference Work"
            return 71

    class _HelpTrackService:
        def create_track(self, payload):
            assert payload.work_id == 71
            help_create_conn.execute(
                "INSERT INTO Tracks(id, track_title) VALUES(73, ?)",
                (payload.track_title,),
            )
            return 73

    created_help_track = scenarios._ensure_help_visual_track(
        SimpleNamespace(
            window=SimpleNamespace(
                track_service=_HelpTrackService(),
                work_service=_HelpWorkService(),
                refresh_table_preserve_view=lambda **kwargs: refresh_calls.append(kwargs),
            ),
            connection=help_create_conn,
            process_events=lambda **kwargs: refresh_calls.append({"events": kwargs}),
        )
    )
    assert created_help_track == 73
    assert refresh_calls[0] == {"focus_id": 73}
    help_create_conn.close()

    failing_context_window = SimpleNamespace(
        save_button=fake_button,
        _current_work_track_context=lambda: (_ for _ in ()).throw(RuntimeError("context bad")),
    )
    failing_context = scenarios._catalog_track_persistence_failure_context(failing_context_window)
    assert "RuntimeError: context bad" in failing_context

    window = QMainWindow()
    window.setWindowTitle("QA Window")
    window.menuBar().addMenu("File")
    window.conn = conn
    harness.window = window
    scenarios.run_startup_smoke(harness)
    assert harness.evidence.records[-1][0] == "UI-PQ-SMOKE-001"

    harness.window = None
    with pytest.raises(AssertionError, match="window is not open"):
        scenarios.run_startup_smoke(harness)
    harness.window = QMainWindow()
    with pytest.raises(AssertionError, match="No menus"):
        scenarios.run_startup_smoke(harness)
    harness.window.menuBar().addMenu("File")
    with pytest.raises(AssertionError, match="QA database"):
        scenarios.run_startup_smoke(harness)

    harness.inventory = [SimpleNamespace(kind="menu"), SimpleNamespace(kind="action")]
    scenarios.run_menu_inventory(harness)
    assert harness.evidence.records[-1][0] == "UI-PQ-MENU-001"
    harness.inventory = [SimpleNamespace(kind="menu")]
    with pytest.raises(AssertionError, match="No QAction"):
        scenarios.run_menu_inventory(harness)

    monkeypatch.setattr(
        scenarios,
        "validate_help_coverage",
        lambda *_args, **_kwargs: SimpleNamespace(
            status="passed",
            coverage_percent=100,
            chapter_count=1,
            chapter_screenshot_count=1,
            chapter_screenshot_required_count=1,
            chapter_screenshot_exempt_count=0,
        ),
    )
    assert scenarios._require_help_reference(harness, "Workflow")["help_status"] == "passed"
    monkeypatch.setattr(
        scenarios,
        "validate_help_coverage",
        lambda *_args, **_kwargs: SimpleNamespace(status="failed", finding_count=2),
    )
    with pytest.raises(AssertionError, match="Help documentation coverage"):
        scenarios._require_help_reference(harness, "Workflow")

    conn.close()


def test_scenario_defensive_workflow_guards_and_pending_evidence() -> None:
    _app()

    panel = object()
    assert scenarios._asset_panel_from_window(SimpleNamespace(asset_registry_panel=panel)) is panel
    assert (
        scenarios._asset_panel_from_window(
            SimpleNamespace(
                asset_registry_panel=None, asset_registry_dock=SimpleNamespace(widget=lambda: panel)
            )
        )
        is panel
    )
    assert scenarios._asset_panel_from_window(SimpleNamespace()) is None

    with pytest.raises(AssertionError, match="Application window"):
        scenarios.run_assets_deliverables_workflow(SimpleNamespace(window=None), track_id=1)
    with pytest.raises(AssertionError, match="Asset service"):
        scenarios.run_assets_deliverables_workflow(
            SimpleNamespace(window=SimpleNamespace()), track_id=1
        )
    with pytest.raises(AssertionError, match="catalog track id"):
        scenarios.run_assets_deliverables_workflow(
            SimpleNamespace(window=SimpleNamespace(asset_service=object())),
            track_id=0,
        )
    with pytest.raises(AssertionError, match="open application window"):
        scenarios.run_authenticity_workflow(SimpleNamespace(window=None), track_id=1)
    with pytest.raises(AssertionError, match="Audio authenticity service"):
        scenarios.run_authenticity_workflow(SimpleNamespace(window=SimpleNamespace()), track_id=1)
    with pytest.raises(AssertionError, match="Authenticity key service"):
        scenarios.run_authenticity_workflow(
            SimpleNamespace(window=SimpleNamespace(audio_authenticity_service=object())),
            track_id=1,
        )
    with pytest.raises(AssertionError, match="open application window"):
        scenarios.run_media_audio_workflow(SimpleNamespace(window=None), track_id=1)
    with pytest.raises(AssertionError, match="Track service"):
        scenarios.run_media_audio_workflow(SimpleNamespace(window=SimpleNamespace()), track_id=1)

    deviation_records: list[dict[str, object]] = []
    evidence = _Evidence()
    evidence.evidence_path = "evidence.json"
    harness = SimpleNamespace(
        inventory=[
            SimpleNamespace(inventory_id="asset.action", ui_area="assets"),
            SimpleNamespace(inventory_id="asset.button", ui_area="assets"),
        ],
        evidence=evidence,
        deviations=SimpleNamespace(add=lambda **kwargs: deviation_records.append(kwargs)),
        database_path="qa.db",
    )
    scenarios.run_pending_area(
        harness,
        test_id="UI-PQ-ASSET-PENDING",
        ui_area="assets",
        message="Assets pending",
    )
    scenarios.run_pending_area(
        harness,
        test_id="UI-PQ-MISSING-PENDING",
        ui_area="missing",
        message="Missing pending",
    )

    assert harness.evidence.records[0][1] == "partial"
    assert harness.evidence.records[0][3]["sample"] == ["asset.action", "asset.button"]
    assert harness.evidence.records[1][1] == "pending"
    assert [record["test_id"] for record in deviation_records] == [
        "UI-PQ-ASSET-PENDING",
        "UI-PQ-MISSING-PENDING",
    ]


def test_scenario_pq_workflow_guard_branches(monkeypatch, tmp_path: Path) -> None:
    _app()

    with pytest.raises(AssertionError, match="open application window"):
        scenarios.run_diagnostics_workflow(SimpleNamespace(window=None))

    missing_db = tmp_path / "missing.db"
    with pytest.raises(AssertionError, match="database path is not on disk"):
        scenarios.run_diagnostics_workflow(
            SimpleNamespace(window=SimpleNamespace(), database_path=missing_db)
        )

    database_path = tmp_path / "qa.db"
    database_path.write_bytes(b"sqlite")
    with pytest.raises(AssertionError, match="database maintenance"):
        scenarios.run_diagnostics_workflow(
            SimpleNamespace(window=SimpleNamespace(), database_path=database_path)
        )
    with pytest.raises(AssertionError, match="report builder"):
        scenarios.run_diagnostics_workflow(
            SimpleNamespace(
                window=SimpleNamespace(database_maintenance=object()),
                database_path=database_path,
            )
        )

    ok_checks = [
        {"title": "SQLite integrity", "status": "ok"},
        {"title": "Foreign-key consistency", "status": "ok"},
        {"title": "Schema layout", "status": "ok"},
        {"title": "Schema version", "status": "ok"},
    ]
    bad_checks = [*ok_checks[:-1], {"title": "Schema version", "status": "failed"}]
    with pytest.raises(AssertionError, match="Core diagnostics checks"):
        scenarios.run_diagnostics_workflow(
            SimpleNamespace(
                window=SimpleNamespace(
                    database_maintenance=object(),
                    _build_diagnostics_report=lambda **_kwargs: {"checks": bad_checks},
                ),
                database_path=database_path,
            )
        )

    class _Maintenance:
        def __init__(self, results: list[str]) -> None:
            self.results = results

        def verify_integrity(self, _path):
            return self.results.pop(0)

        def create_backup(self, _conn, _path):
            return SimpleNamespace(backup_path=tmp_path / "backup.db")

        def restore_database(self, _backup_path, restore_target):
            Path(restore_target).write_bytes(b"restored")
            return SimpleNamespace(restored_path=restore_target)

    for results, message in (
        (["bad"], "Active QA database integrity failed"),
        (["ok", "bad"], "Diagnostics backup integrity failed"),
        (["ok", "ok", "bad"], "Diagnostics restore target integrity failed"),
    ):
        with pytest.raises(AssertionError, match=message):
            scenarios.run_diagnostics_workflow(
                SimpleNamespace(
                    window=SimpleNamespace(
                        database_maintenance=_Maintenance(list(results)),
                        _build_diagnostics_report=lambda **_kwargs: {"checks": ok_checks},
                    ),
                    connection=object(),
                    artifact_dir=tmp_path,
                    database_path=database_path,
                )
            )

    class _VisualService:
        def __init__(self, artifact_dir, *args, **kwargs) -> None:
            self.artifact_dir = Path(artifact_dir)
            self.captures = []
            self.comparisons = []

        def capture_widget(self, _widget, name):
            path = self.artifact_dir / f"{name}.png"
            path.write_bytes(b"png")
            return SimpleNamespace(path=path)

        def compare_capture_to_baseline(self, _capture):
            return SimpleNamespace(to_dict=lambda: {"status": "matched"})

        def compare_json_report(self, *_args, **_kwargs):
            return SimpleNamespace(to_dict=lambda: {"status": "matched"})

        def write_manifest(self):
            path = self.artifact_dir / "visual_manifest.json"
            path.write_text("{}", encoding="utf-8")
            return path

    monkeypatch.setattr(scenarios, "VisualQualificationService", _VisualService)
    monkeypatch.setattr(scenarios, "help_screenshot_source_dir", lambda: tmp_path / "help-shots")
    monkeypatch.setattr(scenarios, "_ensure_help_visual_track", lambda _harness: 101)
    monkeypatch.setattr(scenarios, "_capture_help_surface", lambda *_args, **_kwargs: None)

    with pytest.raises(AssertionError, match="open application window"):
        scenarios.run_visual_qualification_workflow(SimpleNamespace(window=None))
    with pytest.raises(AssertionError, match="Catalog table workspace"):
        scenarios.run_visual_qualification_workflow(
            SimpleNamespace(
                window=SimpleNamespace(open_catalog_workspace=lambda: None),
                artifact_dir=tmp_path,
            )
        )
    with pytest.raises(AssertionError, match="Add Track workspace"):
        scenarios.run_visual_qualification_workflow(
            SimpleNamespace(
                window=SimpleNamespace(
                    open_catalog_workspace=lambda: QWidget(),
                    open_add_track_workspace=lambda: None,
                ),
                artifact_dir=tmp_path,
            )
        )

    fields_window = SimpleNamespace(
        open_catalog_workspace=lambda: QWidget(),
        open_add_track_workspace=lambda: QWidget(),
        artist_field=QComboBox(),
        album_title_field=QComboBox(),
        genre_field=QComboBox(),
        track_title_field=QLineEdit(),
        track_number_field=QSpinBox(),
        track_len_m=QSpinBox(),
        track_len_s=QSpinBox(),
    )
    for name in (
        "open_release_browser",
        "open_code_registry_workspace",
        "open_promo_code_ledger",
        "open_global_search",
        "open_contract_template_workspace",
        "open_asset_registry",
        "open_invoice_workspace",
        "open_work_manager",
        "open_party_manager",
        "open_contract_manager",
        "open_rights_matrix",
        "open_quality_dashboard",
    ):
        setattr(fields_window, name, (lambda: None) if name == "open_release_browser" else QWidget)
    with pytest.raises(AssertionError, match="release_browser"):
        scenarios.run_visual_qualification_workflow(
            SimpleNamespace(window=fields_window, artifact_dir=tmp_path)
        )

    with pytest.raises(AssertionError, match="open application window"):
        scenarios.run_help_documentation_workflow(SimpleNamespace(window=None))

    help_file = tmp_path / "help.html"
    help_file.write_text("<html>help</html>", encoding="utf-8")
    finding = SimpleNamespace(
        severity="high",
        subject="chapter",
        category="screenshot",
        expected="chapter screenshot",
        actual="missing screenshot",
        recommended_update="refresh screenshot",
    )
    deviation_records: list[dict[str, object]] = []
    monkeypatch.setattr(scenarios, "refresh_help_chapter_screenshots", lambda _path: [])
    monkeypatch.setattr(scenarios, "copy_help_screenshots", lambda _path: [])
    monkeypatch.setattr(
        scenarios,
        "validate_help_coverage",
        lambda *_args, **_kwargs: SimpleNamespace(findings=[finding]),
    )
    monkeypatch.setattr(
        scenarios,
        "write_help_coverage_report",
        lambda path, _report: Path(path),
    )
    with pytest.raises(AssertionError, match="Help documentation coverage failed"):
        scenarios.run_help_documentation_workflow(
            SimpleNamespace(
                window=SimpleNamespace(_ensure_help_file=lambda: help_file),
                artifact_dir=tmp_path,
                inventory=[],
                deviations=SimpleNamespace(add=lambda **kwargs: deviation_records.append(kwargs)),
                database_path="qa.db",
            )
        )
    assert deviation_records[0]["recommended_followup"] == "refresh screenshot"


def test_visual_qualification_helpers_compare_artifacts_and_images(tmp_path: Path) -> None:
    _app()
    service = VisualQualificationService(tmp_path, manifest_name="bad/name.json")

    assert service.manifest_path.name == "bad-name.json"
    assert _safe_name("...") == "artifact"
    assert _normalize_text("a\r\nb") == "a\nb\n"
    assert _escape_html('<tag attr="x">&') == "&lt;tag attr=&quot;x&quot;&gt;&amp;"

    image_path = tmp_path / "sample.png"
    image = QImage(16, 16, QImage.Format.Format_ARGB32)
    image.fill(QColor("white"))
    image.setPixelColor(0, 0, QColor("black"))
    assert image.save(str(image_path), "PNG")
    capture = _capture_from_image_file("sample", image_path)
    assert capture.non_blank

    with pytest.raises(AssertionError, match="Could not reload"):
        _capture_from_image_file("missing", tmp_path / "missing.png")

    comparison = service.compare_capture_to_baseline(capture)
    assert comparison.baseline_created
    assert service.compare_text("Line Endings", "a\r\nb").passed
    assert service.compare_json_report("Report", {"b": 2, "a": 1}).passed

    empty_path = tmp_path / "empty.txt"
    empty_path.write_text("", encoding="utf-8")
    with pytest.raises(AssertionError, match="missing or empty"):
        service.compare_file_to_baseline(
            name="empty",
            actual_path=empty_path,
            comparison_type="text",
        )

    actual_path = service.actual_dir / "diff.txt"
    baseline_path = service.baseline_dir / "diff.txt"
    actual_path.write_text("actual", encoding="utf-8")
    baseline_path.write_text("baseline", encoding="utf-8")
    with pytest.raises(AssertionError, match="comparison failed"):
        service.compare_file_to_baseline(
            name="diff",
            actual_path=actual_path,
            comparison_type="text",
        )

    assert (
        _compare_image_files(tmp_path / "missing-a.png", tmp_path / "missing-b.png")["reason"]
        == "actual or baseline image could not be loaded"
    )
    other_path = tmp_path / "other.png"
    other = QImage(17, 16, QImage.Format.Format_ARGB32)
    other.fill(QColor("white"))
    assert other.save(str(other_path), "PNG")
    assert _compare_image_files(image_path, other_path)["reason"] == "image dimensions differ"

    manifest = service.write_manifest()
    assert manifest.exists()


def test_help_validation_rejects_duplicate_screenshot_hashes(tmp_path: Path) -> None:
    duplicate_payload = b"same screenshot bytes"
    references = tuple(iter_help_chapter_screenshot_references())[:2]
    for reference in references:
        (tmp_path / reference.filename).write_bytes(duplicate_payload)

    report = validate_help_coverage([], screenshot_dir=tmp_path)

    assert report.duplicate_screenshot_hashes
    assert any(finding.category == "screenshot-uniqueness" for finding in report.findings)


def test_major_scenarios_fail_fast_without_required_window() -> None:
    harness = SimpleNamespace(window=None, connection=None)
    ids = fixtures.QARepertoireIds(1, 2, 3, 4, 5, 6)

    scenario_calls = [
        (scenarios.run_catalog_workflow, (), {}, "window is not open"),
        (scenarios.run_relationship_workflow, (), {"track_id": 1}, "window is not open"),
        (scenarios.run_contract_workflow, (ids,), {}, "window is not open"),
        (scenarios.run_accounting_workflow, (ids,), {}, "open application window"),
        (scenarios.run_diagnostics_workflow, (), {}, "open application window"),
        (scenarios.run_visual_qualification_workflow, (), {}, "open application window"),
        (scenarios.run_help_documentation_workflow, (), {}, "open application window"),
    ]
    for func, args, kwargs, message in scenario_calls:
        with pytest.raises(AssertionError, match=message):
            func(harness, *args, **kwargs)
