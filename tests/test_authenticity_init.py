import importlib
import unittest
from types import SimpleNamespace
from unittest import mock


class TestAuthenticityInit(unittest.TestCase):
    def test_authenticity_module_exports_core_contract(self):
        from isrc_manager import authenticity

        self.assertTrue(hasattr(authenticity, "AUTHENTICITY_SCHEMA_VERSION"))
        self.assertTrue(hasattr(authenticity, "AUTHENTICITY_FEATURE_AVAILABLE"))
        self.assertTrue(hasattr(authenticity, "AuthenticityManifestService"))
        self.assertTrue(hasattr(authenticity, "WatermarkExtractionResult"))

    def test_authenticity_imports_resolve_to_none_when_dependency_unavailable(self):
        from isrc_manager import authenticity

        original_module = importlib.reload(authenticity)
        try:
            with mock.patch(
                "isrc_manager.authenticity.availability.authenticity_dependency_status",
                return_value=SimpleNamespace(available=False),
            ):
                reloaded = importlib.reload(authenticity)

            self.assertFalse(reloaded.AUTHENTICITY_FEATURE_AVAILABLE)
            self.assertIsNone(reloaded.AudioAuthenticityService)
            self.assertIsNone(reloaded.AudioWatermarkService)
            self.assertIsNone(reloaded.AuthenticityKeyService)
            self.assertIsNone(reloaded.AuthenticityManifestService)
            self.assertIsNone(reloaded.AuthenticityExportPreviewDialog)
            self.assertIsNone(reloaded.AuthenticityKeysDialog)
            self.assertIsNone(reloaded.AuthenticityVerificationDialog)
        finally:
            importlib.reload(original_module)
