import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtGui import QAction, QColor, QImage, QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QMainWindow,
    QPushButton,
    QTableView,
    QTableWidget,
    QTableWidgetItem,
)

from isrc_manager.code_registry import CodeRegistryService
from isrc_manager.qa import assertions, commands, fixtures, scenarios
from isrc_manager.qa.deviations import DeviationRecorder
from isrc_manager.qa.evidence import EvidenceRecorder
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
    assert "unknown.button" in trace_path.read_text(encoding="utf-8")
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


def test_scenario_low_level_helpers_cover_success_and_error_edges(monkeypatch) -> None:
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
            status="passed", coverage_percent=100, chapter_count=1, chapter_screenshot_count=1
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
