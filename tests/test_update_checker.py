import json
import unittest

from isrc_manager.update_checker import (
    RELEASE_MANIFEST_URL,
    ReleaseManifest,
    UpdateChecker,
    UpdateCheckError,
    UpdateCheckStatus,
    fetch_release_notes_text,
    resolve_release_notes_fetch_url,
)


def _manifest_bytes(version="3.2.1", **overrides):
    payload = {
        "version": version,
        "released_at": "2026-04-26",
        "summary": "A conservative release summary.",
        "release_notes_url": "https://github.com/cosmowyn/ISRC-Catalog-Manager/blob/main/docs/releases/v3.2.1.md",
        "minimum_supported_version": None,
    }
    payload.update(overrides)
    return json.dumps(payload).encode("utf-8")


class ReleaseManifestTests(unittest.TestCase):
    def test_manifest_parses_valid_payload(self):
        manifest = ReleaseManifest.from_json_bytes(_manifest_bytes())

        self.assertEqual(manifest.version, "3.2.1")
        self.assertEqual(manifest.summary, "A conservative release summary.")

    def test_manifest_rejects_invalid_payload(self):
        invalid_payloads = [
            b"not-json",
            json.dumps({"version": "not-semver"}).encode("utf-8"),
            _manifest_bytes(released_at="26-04-2026"),
            _manifest_bytes(release_notes_url="http://example.com/release"),
        ]

        for payload in invalid_payloads:
            with self.subTest(payload=payload):
                with self.assertRaises(Exception):
                    ReleaseManifest.from_json_bytes(payload)


class UpdateCheckerTests(unittest.TestCase):
    def test_manifest_url_is_centralized_and_https(self):
        self.assertEqual(
            RELEASE_MANIFEST_URL,
            "https://raw.githubusercontent.com/cosmowyn/ISRC-Catalog-Manager/main/docs/releases/latest.json",
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


if __name__ == "__main__":
    unittest.main()
