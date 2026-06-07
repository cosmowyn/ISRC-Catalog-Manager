from __future__ import annotations

import json
from types import SimpleNamespace
from unittest import mock

from PySide6.QtWidgets import QDialog

from isrc_manager import custom_fields as controller
from isrc_manager.file_storage import STORAGE_MODE_DATABASE


def _message_box(messages: list[tuple[str, tuple]]):
    class FakeMessageBox:
        Yes = 1
        No = 2

        @classmethod
        def warning(cls, *args):
            messages.append(("warning", args))

        @classmethod
        def information(cls, *args):
            messages.append(("information", args))

        @classmethod
        def critical(cls, *args):
            messages.append(("critical", args))

        @classmethod
        def question(cls, *args):
            messages.append(("question", args))
            return cls.Yes

    return FakeMessageBox


def test_custom_field_summary_finalizes_blob_icons_and_loads_active_fields():
    fields = [
        {"id": 1, "name": "Mood", "field_type": "text", "options": None},
        {
            "id": 2,
            "name": "Stem",
            "field_type": "blob_audio",
            "options": None,
            "blob_icon_payload": {"mode": "emoji", "emoji": "🎚️"},
        },
    ]
    app = SimpleNamespace(
        custom_field_definitions=SimpleNamespace(list_active_fields=mock.Mock(return_value=fields))
    )

    assert controller.load_active_custom_fields(app) is fields
    summary = controller._custom_field_config_summary(app, fields)

    assert summary[0]["blob_icon_payload"] is None
    assert summary[1]["blob_icon_payload"]["mode"] == "emoji"
    assert summary[1]["blob_icon_payload"]["emoji"]


def test_apply_custom_field_configuration_handles_conflicts_unchanged_success_and_failure(
    monkeypatch,
):
    messages = []
    monkeypatch.setattr(
        controller,
        "_root_attr",
        lambda name, fallback: _message_box(messages) if name == "QMessageBox" else fallback,
    )
    reserved_name = next(iter(controller.PROMOTED_CUSTOM_FIELD_NAMES))
    app = SimpleNamespace(
        active_custom_fields=[{"id": 1, "name": "Mood", "field_type": "text"}],
        _custom_field_config_summary=lambda fields: controller._custom_field_config_summary(
            None, fields
        ),
        custom_field_definitions=SimpleNamespace(sync_fields=mock.Mock()),
        history_manager=None,
        conn=SimpleNamespace(rollback=mock.Mock()),
        logger=mock.Mock(),
        _on_custom_fields_changed=mock.Mock(),
        _audit=mock.Mock(),
        _audit_commit=mock.Mock(),
        _refresh_history_actions=mock.Mock(),
    )

    assert (
        controller._apply_custom_field_configuration(
            app,
            [{"name": reserved_name, "field_type": "text"}],
            action_label="Add",
            action_type="fields.add",
        )
        is False
    )
    assert messages[-1][0] == "warning"
    assert (
        controller._apply_custom_field_configuration(
            app,
            list(app.active_custom_fields),
            action_label="Noop",
            action_type="fields.manage",
        )
        is False
    )

    before = SimpleNamespace(snapshot_id=10)
    after = SimpleNamespace(snapshot_id=11)
    history = SimpleNamespace(
        capture_snapshot=mock.Mock(side_effect=[before, after]),
        record_snapshot_action=mock.Mock(),
        delete_snapshot=mock.Mock(),
    )
    app.history_manager = history
    new_fields = [{"id": 1, "name": "Energy", "field_type": "text"}]
    assert (
        controller._apply_custom_field_configuration(
            app,
            new_fields,
            action_label="Rename",
            action_type="fields.manage",
        )
        is True
    )
    app.custom_field_definitions.sync_fields.assert_called_once_with(
        app.active_custom_fields, new_fields
    )
    app._on_custom_fields_changed.assert_called_once()
    history.record_snapshot_action.assert_called_once()
    app._refresh_history_actions.assert_called_once()

    failed_before = SimpleNamespace(snapshot_id=20)
    app.history_manager = SimpleNamespace(
        capture_snapshot=mock.Mock(return_value=failed_before),
        record_snapshot_action=mock.Mock(),
        delete_snapshot=mock.Mock(),
    )
    app.custom_field_definitions.sync_fields = mock.Mock(side_effect=RuntimeError("sync failed"))
    assert (
        controller._apply_custom_field_configuration(
            app,
            [{"id": 1, "name": "Tempo", "field_type": "text"}],
            action_label="Fail",
            action_type="fields.manage",
        )
        is False
    )
    app.conn.rollback.assert_called_once()
    app.history_manager.delete_snapshot.assert_called_once_with(20)
    app.logger.exception.assert_called()
    assert messages[-1][0] == "critical"


def test_apply_custom_field_configuration_covers_history_and_summary_fallbacks(monkeypatch):
    messages = []
    monkeypatch.setattr(
        controller,
        "_root_attr",
        lambda name, fallback: _message_box(messages) if name == "QMessageBox" else fallback,
    )
    app = SimpleNamespace(
        active_custom_fields=[{"id": 1, "name": "Mood", "field_type": "text"}],
        _custom_field_config_summary=lambda fields: controller._custom_field_config_summary(
            None, fields
        ),
        custom_field_definitions=SimpleNamespace(sync_fields=mock.Mock()),
        history_manager=None,
        conn=SimpleNamespace(rollback=mock.Mock()),
        logger=mock.Mock(),
        _on_custom_fields_changed=mock.Mock(),
        _audit=mock.Mock(),
        _audit_commit=mock.Mock(),
        _refresh_history_actions=mock.Mock(),
    )

    unserializable_fields = [{"id": object(), "name": "Energy", "field_type": "text"}]
    assert (
        controller._apply_custom_field_configuration(
            app,
            unserializable_fields,
            action_label="Rename",
            action_type="fields.manage",
        )
        is True
    )
    app._audit.assert_called_once_with(
        "FIELDS", "CustomFieldDefs", ref_id="batch", details="fields changed"
    )
    app._refresh_history_actions.assert_not_called()

    before = SimpleNamespace(snapshot_id=44)
    app.history_manager = SimpleNamespace(
        capture_snapshot=mock.Mock(return_value=before),
        delete_snapshot=mock.Mock(side_effect=RuntimeError("snapshot delete failed")),
    )
    app.custom_field_definitions.sync_fields = mock.Mock(side_effect=RuntimeError("sync failed"))

    assert (
        controller._apply_custom_field_configuration(
            app,
            [{"id": 1, "name": "Tempo", "field_type": "text"}],
            action_label="Fail",
            action_type="fields.manage",
        )
        is False
    )
    app.history_manager.delete_snapshot.assert_called_once_with(44)
    app.conn.rollback.assert_called_once()
    assert messages[-1][0] == "critical"


def test_prompt_new_custom_field_builds_dropdown_and_blob_fields(monkeypatch):
    messages = []

    class FakeInputDialog:
        text_result = ("Mood", True)
        item_result = ("dropdown", True)
        multiline_result = ("Happy\nSad\nHappy\n", True)

        @classmethod
        def getText(cls, *args):
            return cls.text_result

        @classmethod
        def getItem(cls, *args, **kwargs):
            return cls.item_result

        @classmethod
        def getMultiLineText(cls, *args, **kwargs):
            return cls.multiline_result

    class FakeBlobIconDialog:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def exec(self):
            return QDialog.Accepted

        def current_spec(self):
            return {"mode": "emoji", "emoji": "🎧"}

    def root_attr(name, fallback):
        return {
            "QInputDialog": FakeInputDialog,
            "BlobIconDialog": FakeBlobIconDialog,
            "QMessageBox": _message_box(messages),
        }.get(name, fallback)

    monkeypatch.setattr(controller, "_root_attr", root_attr)
    app = SimpleNamespace(active_custom_fields=[])

    dropdown = controller._prompt_new_custom_field(app)
    assert dropdown["name"] == "Mood"
    assert dropdown["field_type"] == "dropdown"
    assert json.loads(dropdown["options"]) == ["Happy", "Sad", "Happy"]

    FakeInputDialog.text_result = ("Artwork", True)
    FakeInputDialog.item_result = ("blob_audio", True)
    blob = controller._prompt_new_custom_field(app)
    assert blob["field_type"] == "blob_audio"
    assert blob["blob_icon_payload"] == {"mode": "emoji", "emoji": "🎧"}

    FakeInputDialog.text_result = ("Mood", True)
    app.active_custom_fields = [{"name": "Mood"}]
    assert controller._prompt_new_custom_field(app) is None
    assert messages[-1][0] == "warning"


def test_prompt_new_custom_field_covers_cancel_reserved_and_blob_reject(monkeypatch):
    messages = []

    class FakeInputDialog:
        text_result = ("", False)
        item_result = ("text", True)
        multiline_result = ("Ignored", False)

        @classmethod
        def getText(cls, *args):
            return cls.text_result

        @classmethod
        def getItem(cls, *args, **kwargs):
            return cls.item_result

        @classmethod
        def getMultiLineText(cls, *args, **kwargs):
            return cls.multiline_result

    class RejectingBlobIconDialog:
        def __init__(self, *args, **kwargs):
            self.kwargs = kwargs

        def exec(self):
            return QDialog.Rejected

        def current_spec(self):
            raise AssertionError("rejected dialog must not expose an icon spec")

    def root_attr(name, fallback):
        return {
            "QInputDialog": FakeInputDialog,
            "BlobIconDialog": RejectingBlobIconDialog,
            "QMessageBox": _message_box(messages),
        }.get(name, fallback)

    monkeypatch.setattr(controller, "_root_attr", root_attr)
    app = SimpleNamespace(active_custom_fields=[])

    assert controller._prompt_new_custom_field(app) is None

    FakeInputDialog.text_result = (next(iter(controller.PROMOTED_CUSTOM_FIELD_NAMES)), True)
    assert controller._prompt_new_custom_field(app) is None
    assert messages[-1][0] == "warning"

    FakeInputDialog.text_result = ("Tempo", True)
    FakeInputDialog.item_result = ("text", False)
    assert controller._prompt_new_custom_field(app) is None

    FakeInputDialog.item_result = ("dropdown", True)
    dropdown = controller._prompt_new_custom_field(app)
    assert dropdown["options"] is None

    FakeInputDialog.text_result = ("Cover", True)
    FakeInputDialog.item_result = ("blob_image", True)
    blob = controller._prompt_new_custom_field(app)
    assert blob["field_type"] == "blob_image"
    assert blob["blob_icon_payload"] is None


def test_add_remove_and_manage_custom_columns_delegate_to_configuration(monkeypatch):
    messages = []

    class FakeInputDialog:
        @classmethod
        def getItem(cls, *args, **kwargs):
            return ("Mood (text)", True)

    class FakeDialog:
        def __init__(self, fields, app):
            self.fields = fields

        def exec(self):
            return QDialog.Accepted

        def get_fields(self):
            return [{"name": "Managed", "field_type": "text"}]

    def root_attr(name, fallback):
        return {
            "QInputDialog": FakeInputDialog,
            "QMessageBox": _message_box(messages),
            "CustomColumnsDialog": FakeDialog,
        }.get(name, fallback)

    monkeypatch.setattr(controller, "_root_attr", root_attr)
    applied = []
    app = SimpleNamespace(
        active_custom_fields=[{"name": "Mood", "field_type": "text"}],
        _prompt_new_custom_field=mock.Mock(return_value={"name": "Tempo", "field_type": "text"}),
        _apply_custom_field_configuration=lambda fields, **kwargs: applied.append((fields, kwargs)),
    )

    controller.add_custom_column(app)
    controller.remove_custom_column(app)
    controller.manage_custom_columns(app)

    assert applied[0][0][-1]["name"] == "Tempo"
    assert applied[1][0] == []
    assert applied[2][0] == [{"name": "Managed", "field_type": "text"}]

    empty_app = SimpleNamespace(active_custom_fields=[])
    controller.remove_custom_column(empty_app)
    assert messages[-1][0] == "information"


def test_add_remove_and_manage_custom_columns_cover_cancel_paths(monkeypatch):
    messages = []

    class CancelingInputDialog:
        @classmethod
        def getItem(cls, *args, **kwargs):
            return ("", False)

    class NoMessageBox(_message_box(messages)):
        @classmethod
        def question(cls, *args):
            messages.append(("question", args))
            return cls.No

    class RejectedDialog:
        def __init__(self, fields, app):
            self.fields = fields
            self.app = app

        def exec(self):
            return QDialog.Rejected

        def get_fields(self):
            raise AssertionError("rejected dialog must not be queried")

    def root_attr(name, fallback):
        return {
            "QInputDialog": CancelingInputDialog,
            "QMessageBox": NoMessageBox,
            "CustomColumnsDialog": RejectedDialog,
        }.get(name, fallback)

    monkeypatch.setattr(controller, "_root_attr", root_attr)
    app = SimpleNamespace(
        active_custom_fields=[{"name": "Mood", "field_type": "text"}],
        _prompt_new_custom_field=mock.Mock(return_value=None),
        _apply_custom_field_configuration=mock.Mock(),
    )

    controller.add_custom_column(app)
    app._apply_custom_field_configuration.assert_not_called()

    controller.remove_custom_column(app)
    app._apply_custom_field_configuration.assert_not_called()

    CancelingInputDialog.getItem = classmethod(lambda cls, *args, **kwargs: ("Mood (text)", True))
    controller.remove_custom_column(app)
    assert messages[-1][0] == "question"
    app._apply_custom_field_configuration.assert_not_called()

    controller.manage_custom_columns(app)
    app._apply_custom_field_configuration.assert_not_called()


def test_on_custom_fields_changed_logs_header_state_failures():
    class HistorySuspender:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    viewport = SimpleNamespace(update=mock.Mock())
    app = SimpleNamespace(
        _suspend_table_layout_history=mock.Mock(return_value=HistorySuspender()),
        load_active_custom_fields=mock.Mock(return_value=[{"name": "Mood"}]),
        _rebuild_table_headers=mock.Mock(),
        _bind_header_state_signals=mock.Mock(side_effect=RuntimeError("bind failed")),
        _load_header_state=mock.Mock(side_effect=RuntimeError("load failed")),
        _save_header_state=mock.Mock(side_effect=RuntimeError("save failed")),
        logger=mock.Mock(),
        refresh_table=mock.Mock(),
        _sync_catalog_count_label=mock.Mock(),
        table=SimpleNamespace(viewport=mock.Mock(return_value=viewport)),
    )

    controller._on_custom_fields_changed(app)

    assert app.active_custom_fields == [{"name": "Mood"}]
    assert app.logger.warning.call_count == 3
    app.refresh_table.assert_called_once_with()
    viewport.update.assert_called_once_with()


def test_catalog_editor_focus_target_resolves_standard_media_and_field_keys():
    assert controller._catalog_editor_focus_target(None) is None
    assert controller._catalog_editor_focus_target(SimpleNamespace(kind="custom")) is None
    assert (
        controller._catalog_editor_focus_target(
            SimpleNamespace(kind="standard", standard_media_key="audio_file")
        )
        == "audio_file"
    )
    assert (
        controller._catalog_editor_focus_target(
            SimpleNamespace(kind="standard", standard_media_key="", standard_field_key="genre")
        )
        == "genre"
    )


def test_double_click_standard_cell_opens_editor_or_warns(monkeypatch):
    messages = []
    monkeypatch.setattr(
        controller,
        "_root_attr",
        lambda name, fallback: _message_box(messages) if name == "QMessageBox" else fallback,
    )
    catalog_controller = SimpleNamespace(
        cell_target=mock.Mock(
            return_value=SimpleNamespace(
                kind="standard",
                track_id=5,
                standard_media_key="audio_file",
                standard_field_key="",
            )
        )
    )
    app = SimpleNamespace(
        BASE_HEADERS=["Title"],
        active_custom_fields=[],
        _catalog_table_controller=mock.Mock(return_value=catalog_controller),
        _catalog_editor_focus_target=lambda cell: controller._catalog_editor_focus_target(cell),
        open_selected_editor=mock.Mock(),
    )

    controller._on_catalog_index_double_clicked(app, object())
    app.open_selected_editor.assert_called_once_with(5, initial_focus_target="audio_file")

    catalog_controller.cell_target.return_value = SimpleNamespace(kind="standard", track_id=None)
    controller._on_catalog_index_double_clicked(app, object())
    assert messages[-1][0] == "warning"


def test_double_click_custom_cell_ignores_incomplete_targets():
    catalog_controller = SimpleNamespace(
        cell_target=mock.Mock(
            side_effect=[
                SimpleNamespace(
                    kind="custom",
                    track_id=1,
                    custom_field=None,
                    custom_field_id=2,
                    custom_field_type="text",
                ),
                SimpleNamespace(
                    kind="custom",
                    track_id=None,
                    custom_field={"name": "Mood"},
                    custom_field_id=2,
                    custom_field_type="text",
                ),
                SimpleNamespace(
                    kind="custom",
                    track_id=1,
                    custom_field={"name": "Mood"},
                    custom_field_id=None,
                    custom_field_type="text",
                ),
            ]
        )
    )
    app = SimpleNamespace(
        BASE_HEADERS=[],
        active_custom_fields=[],
        _catalog_table_controller=mock.Mock(return_value=catalog_controller),
        custom_field_values=SimpleNamespace(get_text_value=mock.Mock()),
    )

    controller._on_catalog_index_double_clicked(app, object())
    controller._on_catalog_index_double_clicked(app, object())
    controller._on_catalog_index_double_clicked(app, object())

    app.custom_field_values.get_text_value.assert_not_called()


def test_double_click_blob_custom_field_attaches_file_with_storage_choice(monkeypatch, tmp_path):
    messages = []
    audio_path = tmp_path / "audio.wav"
    audio_path.write_bytes(b"RIFF")

    class FakeFileDialog:
        @classmethod
        def getOpenFileName(cls, *args):
            return (str(audio_path), "")

    def root_attr(name, fallback):
        return {
            "QFileDialog": FakeFileDialog,
            "QMessageBox": _message_box(messages),
            "_prompt_storage_mode_choice": lambda *args, **kwargs: STORAGE_MODE_DATABASE,
        }.get(name, fallback)

    monkeypatch.setattr(controller, "_root_attr", root_attr)
    catalog_controller = SimpleNamespace(
        cell_target=mock.Mock(
            return_value=SimpleNamespace(
                kind="custom",
                track_id=9,
                custom_field={"name": "Stem"},
                custom_field_id=3,
                custom_field_type="blob_audio",
            )
        )
    )
    app = SimpleNamespace(
        BASE_HEADERS=[],
        active_custom_fields=[],
        _catalog_table_controller=mock.Mock(return_value=catalog_controller),
        _run_snapshot_history_action=lambda **kwargs: kwargs["mutation"](),
        cf_save_value=mock.Mock(),
        refresh_table_preserve_view=mock.Mock(),
        conn=SimpleNamespace(rollback=mock.Mock()),
        logger=mock.Mock(),
    )

    controller._on_catalog_index_double_clicked(app, object())

    app.cf_save_value.assert_called_once_with(
        9,
        3,
        value=None,
        blob_path=str(audio_path),
        storage_mode=STORAGE_MODE_DATABASE,
    )
    app.refresh_table_preserve_view.assert_called_once_with(focus_id=9)


def test_double_click_blob_custom_field_covers_cancel_and_error_paths(monkeypatch, tmp_path):
    messages = []
    image_path = tmp_path / "cover.png"
    image_path.write_bytes(b"PNG")

    class FakeFileDialog:
        result = (str(image_path), "")

        @classmethod
        def getOpenFileName(cls, *args):
            return cls.result

    storage_choices = [None, STORAGE_MODE_DATABASE]

    def root_attr(name, fallback):
        return {
            "QFileDialog": FakeFileDialog,
            "QMessageBox": _message_box(messages),
            "_prompt_storage_mode_choice": lambda *args, **kwargs: storage_choices.pop(0),
        }.get(name, fallback)

    monkeypatch.setattr(controller, "_root_attr", root_attr)
    catalog_controller = SimpleNamespace(
        cell_target=mock.Mock(
            return_value=SimpleNamespace(
                kind="custom",
                track_id=9,
                custom_field={"name": "Cover"},
                custom_field_id=3,
                custom_field_type="blob_image",
            )
        )
    )
    app = SimpleNamespace(
        BASE_HEADERS=[],
        active_custom_fields=[],
        _catalog_table_controller=mock.Mock(return_value=catalog_controller),
        _run_snapshot_history_action=mock.Mock(),
        cf_save_value=mock.Mock(),
        refresh_table_preserve_view=mock.Mock(),
        conn=SimpleNamespace(rollback=mock.Mock()),
        logger=mock.Mock(),
    )

    FakeFileDialog.result = ("", "")
    controller._on_catalog_index_double_clicked(app, object())
    app._run_snapshot_history_action.assert_not_called()

    FakeFileDialog.result = (str(image_path), "")
    controller._on_catalog_index_double_clicked(app, object())
    app._run_snapshot_history_action.assert_not_called()

    app._run_snapshot_history_action = mock.Mock(side_effect=RuntimeError("save failed"))
    controller._on_catalog_index_double_clicked(app, object())

    app.conn.rollback.assert_called_once_with()
    app.logger.exception.assert_called_once()
    assert messages[-1][0] == "critical"
    app.refresh_table_preserve_view.assert_not_called()


def test_double_click_dropdown_custom_field_updates_options_and_value(monkeypatch):
    class FakeInputDialog:
        @classmethod
        def getItem(cls, *args, **kwargs):
            return ("New Choice", True)

    monkeypatch.setattr(
        controller,
        "_root_attr",
        lambda name, fallback: FakeInputDialog if name == "QInputDialog" else fallback,
    )
    catalog_controller = SimpleNamespace(
        cell_target=mock.Mock(
            return_value=SimpleNamespace(
                kind="custom",
                track_id=4,
                custom_field={"name": "Mood", "options": json.dumps(["Old Choice"])},
                custom_field_id=2,
                custom_field_type="dropdown",
            )
        )
    )
    app = SimpleNamespace(
        BASE_HEADERS=[],
        active_custom_fields=[],
        _catalog_table_controller=mock.Mock(return_value=catalog_controller),
        custom_field_values=SimpleNamespace(
            get_text_value=mock.Mock(return_value="Old Choice"),
            save_value=mock.Mock(),
        ),
        custom_field_definitions=SimpleNamespace(update_dropdown_options=mock.Mock()),
        _run_snapshot_history_action=lambda **kwargs: kwargs["mutation"](),
        refresh_table_preserve_view=mock.Mock(),
        conn=SimpleNamespace(rollback=mock.Mock()),
        logger=mock.Mock(),
    )

    controller._on_catalog_index_double_clicked(app, object())

    app.custom_field_definitions.update_dropdown_options.assert_called_once_with(
        2,
        ["Old Choice", "New Choice"],
    )
    app.custom_field_values.save_value.assert_called_once_with(4, 2, value="New Choice")
    app.refresh_table_preserve_view.assert_called_once_with(focus_id=4)


def test_double_click_custom_field_covers_dropdown_cancel_and_unchanged(monkeypatch):
    class FakeInputDialog:
        item_result = ("", False)

        @classmethod
        def getItem(cls, *args, **kwargs):
            return cls.item_result

    monkeypatch.setattr(
        controller,
        "_root_attr",
        lambda name, fallback: FakeInputDialog if name == "QInputDialog" else fallback,
    )
    catalog_controller = SimpleNamespace(
        cell_target=mock.Mock(
            return_value=SimpleNamespace(
                kind="custom",
                track_id=4,
                custom_field={"name": "Mood", "options": json.dumps(["Known"])},
                custom_field_id=2,
                custom_field_type="dropdown",
            )
        )
    )
    app = SimpleNamespace(
        BASE_HEADERS=[],
        active_custom_fields=[],
        _catalog_table_controller=mock.Mock(return_value=catalog_controller),
        custom_field_values=SimpleNamespace(
            get_text_value=mock.Mock(side_effect=["Legacy", "Known"]),
            save_value=mock.Mock(),
        ),
        custom_field_definitions=SimpleNamespace(update_dropdown_options=mock.Mock()),
        _run_snapshot_history_action=mock.Mock(),
        refresh_table_preserve_view=mock.Mock(),
        conn=SimpleNamespace(rollback=mock.Mock()),
        logger=mock.Mock(),
    )

    controller._on_catalog_index_double_clicked(app, object())
    app._run_snapshot_history_action.assert_not_called()

    FakeInputDialog.item_result = ("Known", True)
    controller._on_catalog_index_double_clicked(app, object())
    app._run_snapshot_history_action.assert_not_called()


def test_double_click_checkbox_date_and_text_custom_fields(monkeypatch):
    class FakeInputDialog:
        item_result = ("False", True)
        multiline_result = ("New notes", True)

        @classmethod
        def getItem(cls, *args, **kwargs):
            return cls.item_result

        @classmethod
        def getMultiLineText(cls, *args, **kwargs):
            return cls.multiline_result

    class FakeDatePickerDialog:
        result = QDialog.Accepted
        selected = "2026-06-07"
        created_with = []

        def __init__(self, *args, **kwargs):
            self.created_with.append(kwargs)

        def exec(self):
            return self.result

        def selected_iso(self):
            return self.selected

    def root_attr(name, fallback):
        return {
            "QInputDialog": FakeInputDialog,
            "DatePickerDialog": FakeDatePickerDialog,
        }.get(name, fallback)

    monkeypatch.setattr(controller, "_root_attr", root_attr)
    targets = [
        SimpleNamespace(
            kind="custom",
            track_id=4,
            custom_field={"name": "Licensed"},
            custom_field_id=2,
            custom_field_type="checkbox",
        ),
        SimpleNamespace(
            kind="custom",
            track_id=4,
            custom_field={"name": "Review Date"},
            custom_field_id=3,
            custom_field_type="date",
        ),
        SimpleNamespace(
            kind="custom",
            track_id=4,
            custom_field={"name": "Notes"},
            custom_field_id=4,
            custom_field_type="text",
        ),
    ]
    catalog_controller = SimpleNamespace(cell_target=mock.Mock(side_effect=targets))
    saved_values = []
    app = SimpleNamespace(
        BASE_HEADERS=[],
        active_custom_fields=[],
        _catalog_table_controller=mock.Mock(return_value=catalog_controller),
        custom_field_values=SimpleNamespace(
            get_text_value=mock.Mock(side_effect=["True", "bad-date", "Old notes"]),
            save_value=mock.Mock(
                side_effect=lambda track, field, *, value: saved_values.append(value)
            ),
        ),
        custom_field_definitions=SimpleNamespace(update_dropdown_options=mock.Mock()),
        _run_snapshot_history_action=lambda **kwargs: kwargs["mutation"](),
        refresh_table_preserve_view=mock.Mock(),
        conn=SimpleNamespace(rollback=mock.Mock()),
        logger=mock.Mock(),
    )

    controller._on_catalog_index_double_clicked(app, object())
    controller._on_catalog_index_double_clicked(app, object())
    controller._on_catalog_index_double_clicked(app, object())

    assert saved_values == ["False", "2026-06-07", "New notes"]
    assert FakeDatePickerDialog.created_with[0]["initial_iso_date"] is None
    assert app.refresh_table_preserve_view.call_count == 3


def test_double_click_date_text_and_save_error_paths(monkeypatch):
    messages = []

    class CancelingInputDialog:
        item_result = ("True", False)
        multiline_result = ("", False)

        @classmethod
        def getItem(cls, *args, **kwargs):
            return cls.item_result

        @classmethod
        def getMultiLineText(cls, *args, **kwargs):
            return cls.multiline_result

    class FakeDatePickerDialog:
        result = QDialog.Rejected
        selected = None

        def __init__(self, *args, **kwargs):
            self.kwargs = kwargs

        def exec(self):
            return self.result

        def selected_iso(self):
            return self.selected

    def root_attr(name, fallback):
        return {
            "QInputDialog": CancelingInputDialog,
            "DatePickerDialog": FakeDatePickerDialog,
            "QMessageBox": _message_box(messages),
        }.get(name, fallback)

    monkeypatch.setattr(controller, "_root_attr", root_attr)
    targets = [
        SimpleNamespace(
            kind="custom",
            track_id=4,
            custom_field={"name": "Licensed"},
            custom_field_id=2,
            custom_field_type="checkbox",
        ),
        SimpleNamespace(
            kind="custom",
            track_id=4,
            custom_field={"name": "Review Date"},
            custom_field_id=3,
            custom_field_type="date",
        ),
        SimpleNamespace(
            kind="custom",
            track_id=4,
            custom_field={"name": "Notes"},
            custom_field_id=4,
            custom_field_type="text",
        ),
        SimpleNamespace(
            kind="custom",
            track_id=4,
            custom_field={"name": "Review Date"},
            custom_field_id=3,
            custom_field_type="date",
        ),
        SimpleNamespace(
            kind="custom",
            track_id=4,
            custom_field={"name": "Notes"},
            custom_field_id=4,
            custom_field_type="text",
        ),
    ]
    catalog_controller = SimpleNamespace(cell_target=mock.Mock(side_effect=targets))
    app = SimpleNamespace(
        BASE_HEADERS=[],
        active_custom_fields=[],
        _catalog_table_controller=mock.Mock(return_value=catalog_controller),
        custom_field_values=SimpleNamespace(
            get_text_value=mock.Mock(
                side_effect=["True", "2026-06-07", "Old notes", "2026-06-07", "Old notes"]
            ),
            save_value=mock.Mock(),
        ),
        custom_field_definitions=SimpleNamespace(update_dropdown_options=mock.Mock()),
        _run_snapshot_history_action=mock.Mock(side_effect=RuntimeError("save failed")),
        refresh_table_preserve_view=mock.Mock(),
        conn=SimpleNamespace(rollback=mock.Mock()),
        logger=mock.Mock(),
    )

    controller._on_catalog_index_double_clicked(app, object())
    controller._on_catalog_index_double_clicked(app, object())
    controller._on_catalog_index_double_clicked(app, object())
    app._run_snapshot_history_action.assert_not_called()

    FakeDatePickerDialog.result = QDialog.Accepted
    FakeDatePickerDialog.selected = None
    controller._on_catalog_index_double_clicked(app, object())

    CancelingInputDialog.multiline_result = ("New notes", True)
    controller._on_catalog_index_double_clicked(app, object())

    assert app.conn.rollback.call_count == 2
    assert app.logger.exception.call_count == 2
    assert messages[-1][0] == "critical"
