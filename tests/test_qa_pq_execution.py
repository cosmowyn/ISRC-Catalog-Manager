from __future__ import annotations

import inspect
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest

from isrc_manager.qa.harness import UIQualificationHarness
from tests import ci_groups, run_module
from tests.ui_qa import conftest as ui_pq_conftest
from tests.ui_qa import test_ui_pq_help_documentation

FULL_STEP_IDS = [
    "UI-PQ-INV-001",
    "UI-PQ-SMOKE-001",
    "UI-PQ-MENU-001",
    "UI-PQ-SET-001",
    "UI-PQ-HELP-001",
    "UI-PQ-CAT-001",
    "UI-PQ-HIST-001",
    "UI-PQ-REL-001",
    "UI-PQ-CON-001",
    "UI-PQ-ACC-001",
    "UI-PQ-SC-001",
    "UI-PQ-DIAG-001",
    "UI-PQ-IMP-001",
    "UI-PQ-ASSET-001",
    "UI-PQ-AUTH-001",
    "UI-PQ-MEDIA-001",
]

GROUPED_PYTEST_MODULE_COUNTS = {
    "tests.test_history_replay_controller": 7,
    "tests.history.test_snapshot_replay_scope": 24,
    "tests.history.test_snapshot_security": 11,
    "tests.test_asset_delete_history": 4,
    "tests.test_party_rights_history": 7,
    "tests.test_credential_reset": 10,
    "tests.test_credential_reset_controller": 5,
}


def _recording_harness(
    *, catalog_succeeds: bool = True
) -> tuple[UIQualificationHarness, list[str]]:
    harness = object.__new__(UIQualificationHarness)
    harness._has_run = False
    harness.qa_data = {}
    step_ids: list[str] = []
    repertoire_ids = SimpleNamespace(
        track_id=41,
        party_id=42,
        work_id=43,
        release_id=44,
        contract_id=45,
        right_id=46,
    )

    def run_step(test_id, _label, _workflow):
        step_ids.append(test_id)
        if test_id == "UI-PQ-CAT-001":
            return 41 if catalog_succeeds else None
        if test_id in {"UI-PQ-REL-001", "UI-PQ-CON-001"}:
            return repertoire_ids
        return None

    harness._run_step = run_step
    harness.finalize = mock.Mock()
    return harness, step_ids


def test_full_execution_preserves_the_complete_scenario_order() -> None:
    harness, step_ids = _recording_harness()

    harness.run_qualification(None)

    assert step_ids == FULL_STEP_IDS
    harness.finalize.assert_called_once_with()


def test_full_entrypoint_delegates_to_component_aware_execution() -> None:
    harness = object.__new__(UIQualificationHarness)
    harness.run_qualification = mock.Mock()

    harness.run_full_qualification()

    harness.run_qualification.assert_called_once_with(None)


def test_qualified_window_geometry_restores_constraints_after_failure() -> None:
    harness = object.__new__(UIQualificationHarness)
    window = mock.Mock()
    old_minimum = object()
    old_maximum = object()
    old_size = object()
    window.minimumSize.return_value = old_minimum
    window.maximumSize.return_value = old_maximum
    window.size.return_value = old_size
    window.minimumWidth.return_value = 1506
    harness.window = window
    harness.process_events = mock.Mock()

    with pytest.raises(RuntimeError, match="capture failed"):
        with harness.qualified_window_geometry():
            window.setFixedSize.assert_called_once_with(1506, 800)
            raise RuntimeError("capture failed")

    window.setMinimumSize.assert_called_once_with(old_minimum)
    window.setMaximumSize.assert_called_once_with(old_maximum)
    window.resize.assert_called_once_with(old_size)
    assert harness.process_events.call_args_list == [mock.call(cycles=8), mock.call(cycles=8)]


def test_isolated_asset_execution_adds_only_its_canonical_dependencies() -> None:
    harness, step_ids = _recording_harness()

    harness.run_qualification(["assets"])

    assert step_ids == [
        "UI-PQ-INV-001",
        "UI-PQ-SMOKE-001",
        "UI-PQ-MENU-001",
        "UI-PQ-CAT-001",
        "UI-PQ-ASSET-001",
    ]
    harness.finalize.assert_called_once_with()


def test_invalid_component_input_is_rejected_before_execution() -> None:
    harness, step_ids = _recording_harness()

    with pytest.raises(ValueError, match="unknown-component"):
        harness.run_qualification(["unknown-component"])
    with pytest.raises(TypeError, match="iterable of component names"):
        harness.run_qualification("assets")

    assert step_ids == []
    harness.finalize.assert_not_called()


def test_execution_finalizes_when_a_selected_prerequisite_fails() -> None:
    harness, step_ids = _recording_harness(catalog_succeeds=False)

    with pytest.raises(RuntimeError, match="require the catalog workflow track id"):
        harness.run_qualification(["assets"])

    assert step_ids == [
        "UI-PQ-INV-001",
        "UI-PQ-SMOKE-001",
        "UI-PQ-MENU-001",
        "UI-PQ-CAT-001",
    ]
    harness.finalize.assert_called_once_with()


def test_ui_pq_fixture_configuration_parses_component_and_artifact_environment() -> None:
    artifact_dir, components = ui_pq_conftest._ui_pq_configuration_from_env(
        {
            "ISRC_UI_PQ_ARTIFACT_DIR": "build/selected-ui-pq",
            "ISRC_UI_PQ_COMPONENTS": '["assets", "catalog"]',
        }
    )
    default_artifact_dir, default_components = ui_pq_conftest._ui_pq_configuration_from_env({})

    assert artifact_dir == Path("build/selected-ui-pq")
    assert components == ("assets", "catalog")
    assert default_artifact_dir == Path("artifacts/ui_pq")
    assert default_components is None


@pytest.mark.parametrize("value", ["not-json", "{}", '["assets", 3]'])
def test_ui_pq_fixture_configuration_rejects_malformed_component_json(value: str) -> None:
    with pytest.raises(pytest.UsageError, match="JSON array of strings"):
        ui_pq_conftest._ui_pq_configuration_from_env({"ISRC_UI_PQ_COMPONENTS": value})


def test_help_documentation_uses_the_shared_session_harness() -> None:
    parameters = inspect.signature(
        test_ui_pq_help_documentation.test_ui_pq_help_documentation_is_fully_validated
    ).parameters

    assert list(parameters) == ["ui_pq_harness"]
    assert not hasattr(test_ui_pq_help_documentation, "help_pq_harness")


def test_grouped_top_level_pytest_modules_are_counted_and_route_to_pytest() -> None:
    grouped_modules = {module for modules in ci_groups.GROUP_MODULES.values() for module in modules}

    for module, expected_count in GROUPED_PYTEST_MODULE_COUNTS.items():
        assert module in grouped_modules
        module_path = run_module._resolve_module_path(module)
        assert ci_groups.count_test_definitions(module_path) == expected_count
        assert unittest.defaultTestLoader.loadTestsFromName(module).countTestCases() == 0


def test_run_module_preserves_nonempty_unittest_execution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    class PassingTest(unittest.TestCase):
        def test_passes(self) -> None:
            pass

    monkeypatch.setattr(
        run_module.unittest.defaultTestLoader,
        "loadTestsFromName",
        lambda _module: unittest.defaultTestLoader.loadTestsFromTestCase(PassingTest),
    )
    module_path = tmp_path / "test_unittest.py"
    module_path.write_text(
        "import unittest\n\n"
        "class PassingTest(unittest.TestCase):\n"
        "    def test_passes(self):\n"
        "        pass\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(run_module, "_resolve_module_path", lambda _module: module_path)
    monkeypatch.setattr(
        run_module,
        "_run_pytest_file",
        lambda _path: pytest.fail("pytest fallback should not run for a unittest suite"),
    )
    monkeypatch.setattr(run_module.faulthandler, "enable", lambda **_kwargs: None)
    monkeypatch.setattr(run_module.faulthandler, "cancel_dump_traceback_later", lambda: None)

    assert run_module.main(["tests.fake_unittest", "--verbosity", "0"]) == 0
    assert "runner=unittest tests=1" in capsys.readouterr().out


def test_run_module_routes_mixed_unittest_and_pytest_module_through_pytest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    class PassingTest(unittest.TestCase):
        def test_unittest_case(self) -> None:
            pass

    module_path = tmp_path / "test_mixed.py"
    module_path.write_text(
        "import unittest\n\n"
        "class PassingTest(unittest.TestCase):\n"
        "    def test_unittest_case(self):\n"
        "        pass\n\n"
        "def test_pytest_function():\n"
        "    assert True\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(run_module, "_resolve_module_path", lambda _module: module_path)
    monkeypatch.setattr(
        run_module.unittest.defaultTestLoader,
        "loadTestsFromName",
        lambda _module: unittest.defaultTestLoader.loadTestsFromTestCase(PassingTest),
    )
    monkeypatch.setattr(run_module.faulthandler, "enable", lambda **_kwargs: None)
    monkeypatch.setattr(run_module.faulthandler, "cancel_dump_traceback_later", lambda: None)
    calls: list[Path] = []
    monkeypatch.setattr(run_module, "_run_pytest_file", lambda path: calls.append(path) or 0)

    assert run_module.main(["tests.fake_mixed", "--verbosity", "0"]) == 0
    assert "runner=pytest definitions=2" in capsys.readouterr().out
    assert calls == [module_path]


@pytest.mark.parametrize("pytest_exit_code", [0, 1, 5])
def test_run_module_pytest_fallback_propagates_result_without_reporting_zero(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    pytest_exit_code: int,
) -> None:
    module_path = tmp_path / "test_fallback.py"
    module_path.write_text("def test_example():\n    assert True\n", encoding="utf-8")
    monkeypatch.setattr(
        run_module.unittest.defaultTestLoader,
        "loadTestsFromName",
        lambda _module: unittest.TestSuite(),
    )
    monkeypatch.setattr(run_module, "_resolve_module_path", lambda _module: module_path)
    monkeypatch.setattr(run_module.faulthandler, "enable", lambda **_kwargs: None)
    monkeypatch.setattr(run_module.faulthandler, "cancel_dump_traceback_later", lambda: None)
    calls: list[Path] = []

    def run_pytest(path: Path) -> int:
        calls.append(path)
        return pytest_exit_code

    monkeypatch.setattr(run_module, "_run_pytest_file", run_pytest)

    assert run_module.main(["tests.fake_pytest", "--verbosity", "0"]) == pytest_exit_code
    output = capsys.readouterr().out
    assert "runner=pytest" in output
    assert "tests=0" not in output
    assert calls == [module_path]


def test_pytest_fallback_disables_inner_coverage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module_path = tmp_path / "test_fallback.py"
    received: list[list[str]] = []

    def pytest_main(args: list[str]) -> int:
        received.append(args)
        return 5

    monkeypatch.setattr(pytest, "main", pytest_main)

    assert run_module._run_pytest_file(module_path) == 5
    assert received == [["--no-cov", str(module_path)]]
