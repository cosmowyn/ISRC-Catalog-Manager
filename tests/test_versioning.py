import unittest

from isrc_manager.version import __version__, current_app_version
from isrc_manager.versioning import SemVerError, bump_version, parse_semver


class SemVerTests(unittest.TestCase):
    def test_parse_and_string_round_trip(self):
        version = parse_semver("1.2.3-alpha.1+build.7")

        self.assertEqual(version.major, 1)
        self.assertEqual(version.minor, 2)
        self.assertEqual(version.patch, 3)
        self.assertEqual(version.prerelease, ("alpha", "1"))
        self.assertEqual(version.build, ("build", "7"))
        self.assertEqual(str(version), "1.2.3-alpha.1+build.7")

    def test_comparison_orders_patch_minor_major_and_prerelease(self):
        ordered = [
            "1.0.0-alpha",
            "1.0.0-alpha.1",
            "1.0.0-alpha.beta",
            "1.0.0-beta",
            "1.0.0",
            "1.0.1",
            "1.1.0",
            "2.0.0",
        ]

        parsed = [parse_semver(value) for value in ordered]

        self.assertEqual(sorted(parsed), parsed)
        self.assertLess(parse_semver("1.0.0+build.1"), parse_semver("1.0.1"))
        self.assertEqual(parse_semver("1.0.0+build.1"), parse_semver("1.0.0+build.2"))

    def test_invalid_versions_are_rejected(self):
        for value in ("", "1", "1.2", "01.2.3", "1.2.3-01", "1.2.3+"):
            with self.subTest(value=value):
                with self.assertRaises(SemVerError):
                    parse_semver(value)

    def test_bump_resets_lower_order_fields(self):
        self.assertEqual(bump_version("1.2.3", "patch"), "1.2.4")
        self.assertEqual(bump_version("1.2.3", "minor"), "1.3.0")
        self.assertEqual(bump_version("1.2.3", "major"), "2.0.0")


class RuntimeVersionTests(unittest.TestCase):
    def test_current_app_version_uses_fallback_when_package_metadata_is_unavailable(self):
        self.assertEqual(
            current_app_version(package_names=("definitely-not-installed",)), __version__
        )


if __name__ == "__main__":
    unittest.main()
