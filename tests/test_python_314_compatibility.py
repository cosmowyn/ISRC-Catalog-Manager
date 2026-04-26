import importlib
import re
import sys
import tempfile
import unittest
from pathlib import Path

from isrc_manager.constants import SCHEMA_TARGET
from isrc_manager.services import DatabaseSchemaService
from isrc_manager.services.db_access import SQLiteConnectionFactory

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PYPROJECT_PATH = PROJECT_ROOT / "pyproject.toml"
REQUIREMENTS_PATH = PROJECT_ROOT / "requirements.txt"
RELEASE_WORKFLOW_PATH = PROJECT_ROOT / ".github" / "workflows" / "release-build.yml"


def _section_text(text: str, section_name: str) -> str:
    match = re.search(rf"(?ms)^\[{re.escape(section_name)}\]\s*$.*?(?=^\[|\Z)", text)
    if match is None:
        raise AssertionError(f"Missing [{section_name}] section")
    return match.group(0)


def _list_values(section: str, key: str) -> list[str]:
    match = re.search(rf"(?ms)^\s*{re.escape(key)}\s*=\s*\[(.*?)^\s*\]", section)
    if match is None:
        raise AssertionError(f"Missing {key} list")
    values = []
    for line in match.group(1).splitlines():
        value = line.strip().rstrip(",")
        if value.startswith('"') and value.endswith('"'):
            values.append(value.strip('"'))
    return values


def _optional_dependency_values(text: str, key: str) -> list[str]:
    section = _section_text(text, "project.optional-dependencies")
    return _list_values(section, key)


class Python314CompatibilityTests(unittest.TestCase):
    def test_python_314_supported_in_project_metadata(self):
        text = PYPROJECT_PATH.read_text(encoding="utf-8")
        project_section = _section_text(text, "project")
        classifiers = _list_values(project_section, "classifiers")

        self.assertIn('requires-python = ">=3.10"', project_section)
        self.assertIn("Programming Language :: Python :: 3.14", classifiers)

    def test_pyinstaller_pin_uses_python_314_supported_release(self):
        pyproject_text = PYPROJECT_PATH.read_text(encoding="utf-8")
        requirements = REQUIREMENTS_PATH.read_text(encoding="utf-8").splitlines()

        self.assertIn("pyinstaller==6.19.0", _optional_dependency_values(pyproject_text, "build"))
        self.assertIn("pyinstaller==6.19.0", requirements)

    def test_setuptools_package_list_covers_all_isrc_manager_packages(self):
        text = PYPROJECT_PATH.read_text(encoding="utf-8")
        setuptools_section = _section_text(text, "tool.setuptools")
        declared = set(_list_values(setuptools_section, "packages"))
        discovered = {
            str(path.parent.relative_to(PROJECT_ROOT)).replace("/", ".")
            for path in (PROJECT_ROOT / "isrc_manager").rglob("__init__.py")
        }

        self.assertEqual(declared, discovered)

    def test_core_runtime_and_build_modules_import(self):
        modules = (
            "ISRC_manager",
            "build",
            "isrc_manager.version",
            "isrc_manager.versioning",
            "isrc_manager.update_checker",
            "scripts.release_automation",
        )

        for module_name in modules:
            with self.subTest(module=module_name):
                self.assertIsNotNone(importlib.import_module(module_name))

    def test_sqlite_database_initialization_reaches_current_schema(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "profiles" / "compat.db"
            conn = SQLiteConnectionFactory().open(db_path)
            try:
                schema = DatabaseSchemaService(conn, data_root=Path(tmpdir))
                schema.init_db()
                schema.migrate_schema()

                user_version = int(conn.execute("PRAGMA user_version").fetchone()[0])
                table_names = {
                    str(row[0])
                    for row in conn.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    ).fetchall()
                }
            finally:
                conn.close()

        self.assertEqual(user_version, SCHEMA_TARGET)
        self.assertTrue({"Tracks", "Works", "Releases"}.issubset(table_names))

    def test_release_build_workflow_pins_online_packages_to_python_3144(self):
        workflow = RELEASE_WORKFLOW_PATH.read_text(encoding="utf-8")

        self.assertIn('python-version: "3.14.4"', workflow)
        self.assertIn("sys.version_info[:3] != (3, 14, 4)", workflow)

    def test_local_python_3144_environment_when_running_under_314(self):
        if sys.version_info[:2] != (3, 14):
            self.skipTest("Exact Python 3.14.4 assertion only applies to Python 3.14 runs")

        self.assertEqual(sys.version_info[:3], (3, 14, 4))


if __name__ == "__main__":
    unittest.main()
