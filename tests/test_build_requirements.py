import tempfile
import unittest
from pathlib import Path

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


if __name__ == "__main__":
    unittest.main()

