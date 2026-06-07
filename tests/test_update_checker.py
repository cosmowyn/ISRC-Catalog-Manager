import json
import unittest
from unittest import mock

from isrc_manager.update_checker import (
    MAX_MANIFEST_BYTES,
    MAX_RELEASE_NOTES_BYTES,
    RELEASE_MANIFEST_URL,
    ReleaseAsset,
    ReleaseManifest,
    UpdateChecker,
    UpdateCheckError,
    UpdateCheckStatus,
    fetch_manifest_bytes,
    fetch_release_notes_text,
    resolve_release_notes_fetch_url,
)


def _manifest_bytes(version="3.2.1", **overrides):
    tag = f"v{version}"
    payload = {
        "version": version,
        "released_at": "2026-04-26",
        "summary": "A conservative release summary.",
        "release_notes_url": (
            "https://github.com/cosmowyn/ISRC-Catalog-Manager/" f"blob/main/docs/releases/{tag}.md"
        ),
        "minimum_supported_version": None,
        "assets": {
            "windows": {
                "name": f"ISRCManager-{tag}-windows-x64.zip",
                "url": (
                    "https://github.com/cosmowyn/ISRC-Catalog-Manager/"
                    f"releases/download/{tag}/ISRCManager-{tag}-windows-x64.zip"
                ),
                "sha256": "a" * 64,
            },
            "macos": {
                "name": f"ISRCManager-{tag}-macos-arm64.zip",
                "url": (
                    "https://github.com/cosmowyn/ISRC-Catalog-Manager/"
                    f"releases/download/{tag}/ISRCManager-{tag}-macos-arm64.zip"
                ),
                "sha256": "b" * 64,
            },
            "linux": {
                "name": f"ISRCManager-{tag}-linux-x64.tar.gz",
                "url": (
                    "https://github.com/cosmowyn/ISRC-Catalog-Manager/"
                    f"releases/download/{tag}/ISRCManager-{tag}-linux-x64.tar.gz"
                ),
                "sha256": "c" * 64,
            },
        },
    }
    payload.update(overrides)
    return json.dumps(payload).encode("utf-8")


class _FakeUrlopenResponse:
    def __init__(self, data):
        self.data = data
        self.read_size = None

    def __enter__(self):
        return self

    def __exit__(self, *_exc_info):
        return False

    def read(self, size=-1):
        self.read_size = size
        return self.data


class ReleaseManifestTests(unittest.TestCase):
    def test_manifest_parses_valid_payload(self):
        manifest = ReleaseManifest.from_json_bytes(_manifest_bytes())

        self.assertEqual(manifest.version, "3.2.1")
        self.assertEqual(manifest.summary, "A conservative release summary.")
        self.assertIsInstance(manifest.asset_for_platform("macos"), ReleaseAsset)
        self.assertEqual(
            manifest.asset_for_platform("linux").name,
            "ISRCManager-v3.2.1-linux-x64.tar.gz",
        )

    def test_manifest_parses_minimum_supported_version(self):
        manifest = ReleaseManifest.from_json_bytes(
            _manifest_bytes(minimum_supported_version="3.0.0")
        )

        self.assertEqual(manifest.minimum_supported_version, "3.0.0")

    def test_manifest_rejects_invalid_payload(self):
        invalid_payloads = [
            b"not-json",
            b'"not-a-mapping"',
            json.dumps({"version": "not-semver"}).encode("utf-8"),
            _manifest_bytes(summary=""),
            _manifest_bytes(released_at="26-04-2026"),
            _manifest_bytes(release_notes_url="http://example.com/release"),
            _manifest_bytes(assets=None),
            _manifest_bytes(assets={}),
            _manifest_bytes(
                assets={
                    "windows": {
                        "name": "ISRCManager-v3.2.1-windows-x64.zip",
                        "url": (
                            "https://github.com/cosmowyn/ISRC-Catalog-Manager/"
                            "releases/download/v3.2.1/ISRCManager-v3.2.1-windows-x64.zip"
                        ),
                        "sha256": "a" * 64,
                    },
                    "macos": {
                        "name": "ISRCManager-v3.2.1-macos-arm64.zip",
                        "url": (
                            "https://github.com/cosmowyn/ISRC-Catalog-Manager/"
                            "releases/download/v3.2.1/ISRCManager-v3.2.1-macos-arm64.zip"
                        ),
                        "sha256": "not-a-digest",
                    },
                    "linux": {
                        "name": "ISRCManager-v3.2.1-linux-x64.tar.gz",
                        "url": (
                            "https://github.com/cosmowyn/ISRC-Catalog-Manager/"
                            "releases/download/v3.2.1/ISRCManager-v3.2.1-linux-x64.tar.gz"
                        ),
                        "sha256": "c" * 64,
                    },
                }
            ),
        ]

        for payload in invalid_payloads:
            with self.subTest(payload=payload):
                with self.assertRaises(Exception):
                    ReleaseManifest.from_json_bytes(payload)

    def test_manifest_rejects_invalid_asset_payloads(self):
        invalid_payloads = [
            object(),
            {
                "name": "ISRCManager-v3.2.1/windows-x64.zip",
                "url": (
                    "https://github.com/cosmowyn/ISRC-Catalog-Manager/"
                    "releases/download/v3.2.1/ISRCManager-v3.2.1-windows-x64.zip"
                ),
                "sha256": "a" * 64,
            },
        ]

        for payload in invalid_payloads:
            with self.subTest(payload=payload):
                with self.assertRaises(UpdateCheckError):
                    ReleaseAsset.from_mapping("windows", payload)

    def test_manifest_rejects_unsupported_platform_assets(self):
        payload = json.loads(_manifest_bytes().decode("utf-8"))
        payload["assets"]["freebsd"] = {
            "name": "ISRCManager-v3.2.1-freebsd-x64.tar.gz",
            "url": (
                "https://github.com/cosmowyn/ISRC-Catalog-Manager/"
                "releases/download/v3.2.1/ISRCManager-v3.2.1-freebsd-x64.tar.gz"
            ),
            "sha256": "d" * 64,
        }

        with self.assertRaisesRegex(UpdateCheckError, "unsupported platform"):
            ReleaseManifest.from_mapping(payload)

    def test_manifest_rejects_asset_names_and_urls_for_other_versions(self):
        payload = json.loads(_manifest_bytes().decode("utf-8"))
        payload["assets"]["windows"]["name"] = "ISRCManager-v9.9.9-windows-x64.zip"

        with self.assertRaisesRegex(UpdateCheckError, "does not match release"):
            ReleaseManifest.from_mapping(payload)

    def test_manifest_reports_missing_platform_assets(self):
        payload = json.loads(_manifest_bytes().decode("utf-8"))
        del payload["assets"]["linux"]

        with self.assertRaisesRegex(UpdateCheckError, "missing the linux asset"):
            ReleaseManifest.from_mapping(payload)

    def test_manifest_reports_missing_platform_downloads(self):
        manifest = ReleaseManifest.from_json_bytes(_manifest_bytes())

        with self.assertRaisesRegex(UpdateCheckError, "this platform"):
            manifest.asset_for_platform("")


class UpdateCheckerTests(unittest.TestCase):
    def test_manifest_url_is_centralized_and_https(self):
        self.assertEqual(
            RELEASE_MANIFEST_URL,
            "https://github.com/cosmowyn/ISRC-Catalog-Manager/releases/latest/download/latest.json",
        )

    def test_newer_version_available(self):
        checker = UpdateChecker(fetcher=lambda _url, _timeout: _manifest_bytes("3.3.0"))

        result = checker.check("3.2.0")

        self.assertEqual(result.status, UpdateCheckStatus.UPDATE_AVAILABLE)
        self.assertTrue(result.update_available)
        self.assertEqual(result.latest_version, "3.3.0")

    def test_current_and_older_remote_versions_are_not_updates(self):
        for remote_version in ("3.2.0", "3.1.9"):
            with self.subTest(remote_version=remote_version):
                checker = UpdateChecker(
                    fetcher=lambda _url, _timeout, version=remote_version: _manifest_bytes(version)
                )

                result = checker.check("3.2.0")

                self.assertEqual(result.status, UpdateCheckStatus.CURRENT)

    def test_ignored_version_suppresses_startup_result(self):
        checker = UpdateChecker(fetcher=lambda _url, _timeout: _manifest_bytes("3.3.0"))

        result = checker.check("3.2.0", ignored_version="3.3.0")

        self.assertEqual(result.status, UpdateCheckStatus.IGNORED)

    def test_invalid_metadata_and_network_failure_fail_safely(self):
        cases = [
            lambda _url, _timeout: b"{",
            lambda _url, _timeout: (_ for _ in ()).throw(TimeoutError("timeout")),
        ]

        for fetcher in cases:
            with self.subTest(fetcher=fetcher):
                checker = UpdateChecker(fetcher=fetcher)

                result = checker.check("3.2.0")

                self.assertEqual(result.status, UpdateCheckStatus.FAILED)
                self.assertFalse(result.update_available)

    def test_invalid_current_version_fails_without_fetching(self):
        fetcher = mock.Mock(return_value=_manifest_bytes("3.3.0"))
        checker = UpdateChecker(fetcher=fetcher)

        result = checker.check("not-semver")

        self.assertEqual(result.status, UpdateCheckStatus.FAILED)
        self.assertEqual(result.message, "The installed app version is not valid.")
        fetcher.assert_not_called()

    def test_invalid_ignored_version_is_ignored(self):
        checker = UpdateChecker(fetcher=lambda _url, _timeout: _manifest_bytes("3.3.0"))

        result = checker.check("3.2.0", ignored_version="not-semver")

        self.assertEqual(result.status, UpdateCheckStatus.UPDATE_AVAILABLE)
        self.assertEqual(result.latest_version, "3.3.0")


class ReleaseNotesFetchTests(unittest.TestCase):
    def test_github_blob_release_note_url_resolves_to_raw_content_url(self):
        url = (
            "https://github.com/cosmowyn/ISRC-Catalog-Manager/" "blob/main/docs/releases/v3.3.1.md"
        )

        self.assertEqual(
            resolve_release_notes_fetch_url(url),
            (
                "https://raw.githubusercontent.com/cosmowyn/ISRC-Catalog-Manager/"
                "main/docs/releases/v3.3.1.md"
            ),
        )

    def test_non_blob_github_release_note_url_is_left_unchanged(self):
        url = "https://github.com/cosmowyn/ISRC-Catalog-Manager/releases/tag/v3.3.1"

        self.assertEqual(resolve_release_notes_fetch_url(url), url)

    def test_release_notes_fetch_decodes_markdown_from_resolved_url(self):
        calls = []
        blob_url = (
            "https://github.com/cosmowyn/ISRC-Catalog-Manager/" "blob/main/docs/releases/v3.3.1.md"
        )

        def _fetcher(url, timeout):
            calls.append((url, timeout))
            return b"# Release Notes\n\nLoaded internally."

        text = fetch_release_notes_text(blob_url, 9.0, fetcher=_fetcher)

        self.assertEqual(text, "# Release Notes\n\nLoaded internally.")
        self.assertEqual(
            calls,
            [
                (
                    "https://raw.githubusercontent.com/cosmowyn/ISRC-Catalog-Manager/"
                    "main/docs/releases/v3.3.1.md",
                    9.0,
                )
            ],
        )

    def test_release_notes_fetch_rejects_non_https_urls(self):
        with self.assertRaises(UpdateCheckError):
            fetch_release_notes_text(
                "http://github.com/cosmowyn/ISRC-Catalog-Manager/blob/main/docs/releases/v3.3.1.md",
                fetcher=lambda _url, _timeout: b"",
            )

    def test_release_notes_fetch_uses_default_https_fetcher(self):
        response = _FakeUrlopenResponse(b"  # Notes\n")

        with mock.patch(
            "isrc_manager.update_checker.urllib.request.urlopen",
            return_value=response,
        ) as urlopen:
            text = fetch_release_notes_text("https://example.com/releases/v3.3.1.md", 2.5)

        self.assertEqual(text, "# Notes")
        self.assertEqual(response.read_size, MAX_RELEASE_NOTES_BYTES + 1)
        self.assertEqual(urlopen.call_args.kwargs["timeout"], 2.5)

    def test_release_notes_fetch_rejects_oversized_notes(self):
        with self.assertRaisesRegex(UpdateCheckError, "too large"):
            fetch_release_notes_text(
                "https://example.com/releases/v3.3.1.md",
                fetcher=lambda _url, _timeout: b"x" * (MAX_RELEASE_NOTES_BYTES + 1),
            )

    def test_release_notes_fetch_wraps_decode_errors(self):
        with self.assertRaisesRegex(UpdateCheckError, "could not be decoded"):
            fetch_release_notes_text(
                "https://example.com/releases/v3.3.1.md",
                fetcher=lambda _url, _timeout: b"\xff\xfe\xff",
            )


class ManifestFetchTests(unittest.TestCase):
    def test_fetch_manifest_bytes_uses_https_request_and_size_limit(self):
        response = _FakeUrlopenResponse(b'{"ok": true}')

        with mock.patch(
            "isrc_manager.update_checker.urllib.request.urlopen",
            return_value=response,
        ) as urlopen:
            data = fetch_manifest_bytes("https://example.com/latest.json", 3.0)

        self.assertEqual(data, b'{"ok": true}')
        self.assertEqual(response.read_size, MAX_MANIFEST_BYTES + 1)
        self.assertEqual(urlopen.call_args.kwargs["timeout"], 3.0)

    def test_fetch_manifest_bytes_wraps_network_errors(self):
        with mock.patch(
            "isrc_manager.update_checker.urllib.request.urlopen",
            side_effect=TimeoutError("slow"),
        ):
            with self.assertRaisesRegex(UpdateCheckError, "unavailable"):
                fetch_manifest_bytes("https://example.com/latest.json", 3.0)

    def test_fetch_manifest_bytes_rejects_oversized_manifest(self):
        response = _FakeUrlopenResponse(b"x" * (MAX_MANIFEST_BYTES + 1))

        with mock.patch(
            "isrc_manager.update_checker.urllib.request.urlopen",
            return_value=response,
        ):
            with self.assertRaisesRegex(UpdateCheckError, "too large"):
                fetch_manifest_bytes("https://example.com/latest.json", 3.0)


if __name__ == "__main__":
    unittest.main()
