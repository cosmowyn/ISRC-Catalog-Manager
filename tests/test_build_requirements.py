import tempfile
import unittest
from pathlib import Path
from unittest import mock

import build
from build import ensure_requirements


class EnsureRequirementsTests(unittest.TestCase):
    def test_creates_default_requirements_with_runtime_and_build_deps(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = Path(tmpdir)
            req = ensure_requirements(project_dir)

            contents = req.read_text(encoding="utf-8")

        self.assertIn("PySide6==6.9.1", contents)
        self.assertIn("pyinstaller==6.15.0", contents)
        self.assertIn("audioread==3.0.1", contents)
        self.assertIn("pillow==12.0.0", contents)
        self.assertIn("openpyxl==3.1.5", contents)
        self.assertIn("mutagen==1.47.0", contents)

    def test_locate_built_artifact_returns_expected_candidate_when_missing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            with (
                mock.patch.object(build, "PROJECT_ROOT", project_root),
                mock.patch.object(build.platform, "system", return_value="Linux"),
            ):
                candidate = build.locate_built_artifact(onefile=True, console=False)

        self.assertEqual(candidate, project_root / "dist" / build.APP_NAME)

    def test_install_artifact_creates_launcher_for_unix_onefile_binary(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            artifact = root / build.APP_NAME
            artifact.write_text("binary", encoding="utf-8")
            install_root = root / "install"

            with mock.patch.object(build.platform, "system", return_value="Linux"):
                build.install_artifact(artifact, install_root)

            installed = install_root / build.APP_NAME
            launcher = install_root / f"run_{build.APP_NAME.lower()}"
            self.assertTrue(installed.exists())
            self.assertTrue(launcher.exists())
            self.assertIn(build.APP_NAME, launcher.read_text(encoding="utf-8"))

    def test_main_env_only_skips_build_steps(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            venv_path = project_root / ".venv"
            (venv_path / "bin").mkdir(parents=True, exist_ok=True)
            requirements_path = project_root / "requirements.txt"
            requirements_path.write_text("PySide6==6.9.1\n", encoding="utf-8")

            with (
                mock.patch.object(build, "PROJECT_ROOT", project_root),
                mock.patch.object(build, "create_venv") as create_venv,
                mock.patch.object(build, "reexec_in_dotvenv_if_found") as reexec,
                mock.patch.object(build, "ask_build_mode", return_value="env_only"),
                mock.patch.object(build, "ensure_requirements", return_value=requirements_path),
                mock.patch.object(build, "venv_python", return_value=venv_path / "bin" / "python"),
                mock.patch.object(build, "pip_install") as pip_install,
                mock.patch.object(build, "ensure_pyinstaller") as ensure_pyinstaller,
                mock.patch.object(build, "build_binary") as build_binary,
                mock.patch.object(build, "destroy_tk_root") as destroy_tk_root,
            ):
                build.main()

        create_venv.assert_not_called()
        reexec.assert_called_once()
        pip_install.assert_called_once()
        ensure_pyinstaller.assert_not_called()
        build_binary.assert_not_called()
        destroy_tk_root.assert_called_once()

    def test_main_build_mode_runs_build_and_install_flow(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            venv_path = project_root / ".venv"
            (venv_path / "bin").mkdir(parents=True, exist_ok=True)
            requirements_path = project_root / "requirements.txt"
            requirements_path.write_text("PySide6==6.9.1\n", encoding="utf-8")
            artifact = project_root / "dist" / build.APP_NAME
            artifact.parent.mkdir(parents=True, exist_ok=True)
            artifact.write_text("binary", encoding="utf-8")
            install_root = project_root / "installed"

            with (
                mock.patch.object(build, "PROJECT_ROOT", project_root),
                mock.patch.object(build, "create_venv"),
                mock.patch.object(build, "reexec_in_dotvenv_if_found"),
                mock.patch.object(build, "ask_build_mode", return_value="build"),
                mock.patch.object(build, "ensure_requirements", return_value=requirements_path),
                mock.patch.object(build, "venv_python", return_value=venv_path / "bin" / "python"),
                mock.patch.object(build, "pip_install"),
                mock.patch.object(build, "ensure_pyinstaller") as ensure_pyinstaller,
                mock.patch.object(build, "_pick_build_options_by_os", return_value=(True, False)),
                mock.patch.object(build, "build_binary") as build_binary,
                mock.patch.object(build, "locate_built_artifact", return_value=artifact),
                mock.patch.object(build, "pick_install_dir", return_value=install_root),
                mock.patch.object(build, "install_artifact") as install_artifact,
                mock.patch.object(build, "destroy_tk_root") as destroy_tk_root,
                mock.patch.object(build.platform, "system", return_value="Linux"),
            ):
                build.main()

        ensure_pyinstaller.assert_called_once()
        build_binary.assert_called_once_with(onefile=True, console=False)
        install_artifact.assert_called_once_with(artifact, install_root)
        destroy_tk_root.assert_called_once()


if __name__ == "__main__":
    unittest.main()
