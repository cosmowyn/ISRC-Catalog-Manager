import unittest
from dataclasses import dataclass

from isrc_manager.integrations.soundcloud.models import (
    SoundCloudPlanAction,
    SoundCloudPlanItemStatus,
    SoundCloudPreflightIssueCode,
    SoundCloudPublishOptions,
    SoundCloudPublishPlanItem,
    SoundCloudQuotaSnapshot,
)
from isrc_manager.integrations.soundcloud.service import (
    AUDIO_BYTES_LIMIT,
    AUDIO_DURATION_LIMIT_SECONDS,
    SoundCloudPublishPlanner,
)


@dataclass(slots=True)
class FakeMediaHandle:
    filename: str
    mime_type: str | None = None
    source_path: str | None = None
    size_bytes: int = 0


class FakeTrackSnapshotProvider:
    def __init__(self, snapshots: dict[int, dict[str, object]]):
        self.snapshots = snapshots

    def get_track_snapshot(self, track_id: int):
        return self.snapshots.get(track_id)


class FakeReleaseSummaryProvider:
    def __init__(self, summaries: dict[int, dict[str, object]]):
        self.summaries = summaries

    def get_release_summary(self, track_id: int):
        return self.summaries.get(track_id)


class FakeMediaProvider:
    def __init__(
        self,
        audio_handles: dict[int, FakeMediaHandle],
        artwork_handles: dict[int, tuple[FakeMediaHandle | None, bool]],
    ):
        self.audio_handles = audio_handles
        self.artwork_handles = artwork_handles

    def get_audio_handle(self, track_id: int):
        return self.audio_handles.get(track_id)

    def get_effective_artwork_handle(self, track_id: int):
        return self.artwork_handles.get(track_id, (None, False))


class FakePublicationLookup:
    def __init__(self, publications: dict[int, dict[str, object]]):
        self.publications = publications

    def find_publication(self, track_id: int):
        return self.publications.get(track_id)


class FakeAccountState:
    def __init__(self, *, connected: bool = True, quota: SoundCloudQuotaSnapshot | None = None):
        self.connected = connected
        self.quota = quota

    def is_connected(self):
        return self.connected

    def get_quota_snapshot(self):
        return self.quota


class SoundCloudServiceTests(unittest.TestCase):
    def setUp(self):
        self.track_provider = FakeTrackSnapshotProvider({})
        self.release_provider = FakeReleaseSummaryProvider({})
        self.media_provider = FakeMediaProvider({}, {})
        self.publication_lookup = FakePublicationLookup({})
        self.account_state = FakeAccountState(
            connected=True,
            quota=SoundCloudQuotaSnapshot(
                daily_remaining_uploads=200,
                hourly_remaining_uploads=200,
                rate_limit_remaining=50,
            ),
        )
        self.planner = SoundCloudPublishPlanner(
            self.track_provider,
            self.release_provider,
            self.media_provider,
            self.publication_lookup,
            self.account_state,
        )

    def _plan(self, track_ids: list[int], options: SoundCloudPublishOptions | None = None):
        return self.planner.plan_tracks(track_ids, options=options)

    def _issue_codes(self, item: SoundCloudPublishPlanItem) -> list[str]:
        return [issue.code.value for issue in item.issues]

    def test_default_publish_options_match_catalog_policy(self):
        options = SoundCloudPublishOptions()

        self.assertEqual(options.sharing, "private")
        self.assertFalse(options.downloadable)
        self.assertTrue(options.streamable)

    def test_default_publish_options_can_be_inspected_from_plan(self):
        self.track_provider.snapshots[101] = {"track_id": 101, "track_title": "Defaults"}
        self.media_provider.audio_handles[101] = FakeMediaHandle(
            filename="track.wav",
            source_path="/tmp/defaults.wav",
            size_bytes=1024,
            mime_type="audio/wav",
        )
        result = self._plan([101])

        self.assertEqual(result.options.sharing, "private")
        self.assertFalse(result.options.downloadable)
        self.assertTrue(result.options.streamable)

    def test_track_not_found_is_blocked(self):
        item = self._plan([999]).items[0]
        self.assertEqual(item.status, SoundCloudPlanItemStatus.BLOCKED)
        self.assertEqual(item.action, SoundCloudPlanAction.SKIP)
        self.assertIn(SoundCloudPreflightIssueCode.TRACK_NOT_FOUND.value, self._issue_codes(item))

    def test_missing_audio_is_blocking(self):
        self.track_provider.snapshots[1] = {"track_id": 1, "track_title": "No audio"}
        item = self._plan([1]).items[0]
        self.assertEqual(item.action, SoundCloudPlanAction.CREATE)
        self.assertEqual(item.status, SoundCloudPlanItemStatus.BLOCKED)
        self.assertIn(SoundCloudPreflightIssueCode.MISSING_AUDIO.value, self._issue_codes(item))

    def test_audio_filename_without_source_path_is_blocked_before_upload(self):
        self.track_provider.snapshots[44] = {"track_id": 44, "track_title": "Bare Filename"}
        self.media_provider.audio_handles[44] = FakeMediaHandle(
            filename="bare-file.wav",
            source_path=None,
            size_bytes=1024,
            mime_type="audio/wav",
        )

        item = self._plan([44]).items[0]

        self.assertEqual(item.status, SoundCloudPlanItemStatus.BLOCKED)
        self.assertIn(SoundCloudPreflightIssueCode.MISSING_AUDIO.value, self._issue_codes(item))
        self.assertIsNotNone(item.metadata)
        assert item.metadata is not None
        self.assertIsNone(item.metadata.asset_data)

    def test_metadata_mapping_includes_required_fields_and_optional_values(self):
        self.track_provider.snapshots[2] = {
            "track_id": 2,
            "track_title": "Lead Single",
            "genre": "electronic",
            "isrc": "us-abc-12-34567",
            "release_date": "2026-04-01",
        }
        self.release_provider.summaries[2] = {
            "release_title": "Main EP",
            "label_name": "Noir Records",
            "release_date": "2026-04-01",
        }
        self.media_provider.audio_handles[2] = FakeMediaHandle(
            filename="track.wav",
            source_path="/tmp/audio.wav",
            size_bytes=2048,
            mime_type="audio/wav",
        )

        result = self._plan([2])
        item = result.items[0]
        self.assertEqual(item.action, SoundCloudPlanAction.CREATE)
        self.assertIsNotNone(item.metadata)
        self.assertEqual(item.metadata.title, "Lead Single")
        self.assertEqual(item.metadata.asset_data, "/tmp/audio.wav")
        self.assertEqual(item.metadata.genre, "electronic")
        self.assertEqual(item.metadata.isrc, "US-ABC-12-34567")
        self.assertEqual(item.metadata.release_date, "2026-04-01")
        self.assertEqual(item.metadata.release, "Main EP")
        self.assertEqual(item.metadata.label_name, "Noir Records")
        self.assertEqual(item.status, SoundCloudPlanItemStatus.READY)

    def test_missing_optional_metadata_is_omitted(self):
        self.track_provider.snapshots[3] = {"track_id": 3, "track_title": "Minimal"}
        self.media_provider.audio_handles[3] = FakeMediaHandle(
            filename="track.wav",
            source_path="/tmp/minimal.wav",
            size_bytes=128,
            mime_type="audio/wav",
        )

        item = self._plan([3]).items[0]
        self.assertIsNone(item.metadata.genre)
        self.assertIsNone(item.metadata.isrc)
        self.assertIsNone(item.metadata.release_date)
        self.assertIsNone(item.metadata.label_name)
        self.assertIsNone(item.metadata.release)

    def test_blank_title_is_blocking(self):
        self.track_provider.snapshots[4] = {"track_id": 4, "track_title": ""}
        self.media_provider.audio_handles[4] = FakeMediaHandle(
            filename="track.wav",
            source_path="/tmp/blank.wav",
            size_bytes=128,
            mime_type="audio/wav",
        )

        item = self._plan([4]).items[0]
        self.assertEqual(item.status, SoundCloudPlanItemStatus.BLOCKED)
        self.assertIn(SoundCloudPreflightIssueCode.BLANK_TITLE.value, self._issue_codes(item))

    def test_license_validation_rejects_unknown_values(self):
        self.track_provider.snapshots[5] = {
            "track_id": 5,
            "track_title": "License Test",
            "license": "invalid-license",
        }
        self.media_provider.audio_handles[5] = FakeMediaHandle(
            filename="track.wav",
            source_path="/tmp/license.wav",
            size_bytes=100,
            mime_type="audio/wav",
        )

        options = SoundCloudPublishOptions(license="also-invalid")
        item = self._plan([5], options=options).items[0]

        self.assertEqual(item.status, SoundCloudPlanItemStatus.BLOCKED)
        self.assertIn(SoundCloudPreflightIssueCode.LICENSE_INVALID.value, self._issue_codes(item))

    def test_unsupported_metadata_fields_are_warning_guarded(self):
        self.track_provider.snapshots[6] = {
            "track_id": 6,
            "track_title": "Unsupported",
            "bpm": 132,
            "metadata_artist": "Guest",
            "purchase_title": "Buy now",
        }
        self.media_provider.audio_handles[6] = FakeMediaHandle(
            filename="track.wav",
            source_path="/tmp/unsupported.wav",
            size_bytes=100,
            mime_type="audio/wav",
        )

        item = self._plan([6]).items[0]
        self.assertEqual(item.status, SoundCloudPlanItemStatus.WARN)
        self.assertIn(
            SoundCloudPreflightIssueCode.UNSUPPORTED_TRACK_FIELD.value,
            self._issue_codes(item),
        )

    def test_purchase_url_is_explicit_only_per_run(self):
        self.track_provider.snapshots[7] = {
            "track_id": 7,
            "track_title": "Purchase URL",
            "purchase_title": "Album purchase",
        }
        self.media_provider.audio_handles[7] = FakeMediaHandle(
            filename="track.wav",
            source_path="/tmp/purchase.wav",
            size_bytes=100,
            mime_type="audio/wav",
        )
        options = SoundCloudPublishOptions(purchase_url="https://example.com/buy")

        item = self._plan([7], options=options).items[0]

        self.assertEqual(item.metadata is not None, True)
        self.assertFalse(hasattr(item.metadata, "purchase_title"))
        self.assertEqual(options.purchase_url, "https://example.com/buy")

    def test_release_date_conflict_warns_and_omits_release_date(self):
        self.track_provider.snapshots[8] = {
            "track_id": 8,
            "track_title": "Conflicting Date",
            "release_date": "2026-04-01",
        }
        self.release_provider.summaries[8] = {"release_dates": ["2026-03-11", "2026-04-01"]}
        self.media_provider.audio_handles[8] = FakeMediaHandle(
            filename="track.wav",
            source_path="/tmp/conflict.wav",
            size_bytes=100,
            mime_type="audio/wav",
        )

        item = self._plan([8]).items[0]
        self.assertEqual(item.status, SoundCloudPlanItemStatus.WARN)
        self.assertIsNone(item.metadata.release_date)
        self.assertIn(
            SoundCloudPreflightIssueCode.RELEASE_DATE_CONFLICT.value,
            self._issue_codes(item),
        )

    def test_artwork_validation_allows_jpeg_rejects_bmp(self):
        jpeg = FakeMediaHandle(
            filename="cover.jpeg",
            source_path="/tmp/cover.jpeg",
            size_bytes=2000,
            mime_type="image/jpeg",
        )
        bmp = FakeMediaHandle(
            filename="cover.bmp",
            source_path="/tmp/cover.bmp",
            size_bytes=1000,
            mime_type="image/bmp",
        )

        self.track_provider.snapshots[9] = {"track_id": 9, "track_title": "Cover 1"}
        self.track_provider.snapshots[10] = {"track_id": 10, "track_title": "Cover 2"}
        self.media_provider.audio_handles[9] = FakeMediaHandle(
            filename="a.wav",
            source_path="/tmp/a.wav",
            size_bytes=100,
            mime_type="audio/wav",
        )
        self.media_provider.audio_handles[10] = FakeMediaHandle(
            filename="b.wav",
            source_path="/tmp/b.wav",
            size_bytes=100,
            mime_type="audio/wav",
        )
        self.media_provider.artwork_handles[9] = (jpeg, False)
        self.media_provider.artwork_handles[10] = (bmp, False)

        item_jpeg, item_bmp = self._plan([9, 10]).items
        self.assertEqual(item_jpeg.metadata.artwork_data, "/tmp/cover.jpeg")
        self.assertEqual(item_jpeg.metadata.artwork_data, "/tmp/cover.jpeg")
        self.assertNotEqual(item_bmp.status, SoundCloudPlanItemStatus.READY)
        self.assertIn(
            SoundCloudPreflightIssueCode.ARTWORK_UNSUPPORTED.value,
            self._issue_codes(item_bmp),
        )

    def test_artwork_ambiguous_is_warning_and_omitted(self):
        self.track_provider.snapshots[11] = {"track_id": 11, "track_title": "Ambiguous Art"}
        self.media_provider.audio_handles[11] = FakeMediaHandle(
            filename="a.wav",
            source_path="/tmp/a.wav",
            size_bytes=100,
            mime_type="audio/wav",
        )
        self.media_provider.artwork_handles[11] = (
            FakeMediaHandle(
                filename="cover.png",
                source_path="/tmp/cover.png",
                size_bytes=100,
                mime_type="image/png",
            ),
            True,
        )

        item = self._plan([11]).items[0]
        self.assertIsNone(item.metadata.artwork_data)
        self.assertIn(
            SoundCloudPreflightIssueCode.ARTWORK_AMBIGUOUS.value,
            self._issue_codes(item),
        )

    def test_quota_warning_and_block_behaviors(self):
        self.track_provider.snapshots[12] = {"track_id": 12, "track_title": "Quota"}
        self.media_provider.audio_handles[12] = FakeMediaHandle(
            filename="track.wav",
            source_path="/tmp/quota.wav",
            size_bytes=100,
            mime_type="audio/wav",
        )

        self.account_state = FakeAccountState(connected=True, quota=None)
        self.planner = SoundCloudPublishPlanner(
            self.track_provider,
            self.release_provider,
            self.media_provider,
            self.publication_lookup,
            self.account_state,
        )
        items = self._plan([12]).items
        self.assertEqual(items[0].status, SoundCloudPlanItemStatus.WARN)
        self.assertIn(
            SoundCloudPreflightIssueCode.MISSING_QUOTA_SNAPSHOT.value,
            self._issue_codes(items[0]),
        )

        self.account_state = FakeAccountState(
            connected=True,
            quota=SoundCloudQuotaSnapshot(daily_remaining_uploads=0, hourly_remaining_uploads=0),
        )
        self.planner = SoundCloudPublishPlanner(
            self.track_provider,
            self.release_provider,
            self.media_provider,
            self.publication_lookup,
            self.account_state,
        )
        items = self._plan([12]).items
        self.assertEqual(items[0].status, SoundCloudPlanItemStatus.BLOCKED)
        self.assertIn(
            SoundCloudPreflightIssueCode.EXPLICIT_QUOTA_EXHAUSTION.value,
            self._issue_codes(items[0]),
        )

    def test_rate_limit_warning_is_present_when_low(self):
        self.track_provider.snapshots[13] = {"track_id": 13, "track_title": "Rate limit warning"}
        self.media_provider.audio_handles[13] = FakeMediaHandle(
            filename="track.wav",
            source_path="/tmp/rate.wav",
            size_bytes=100,
            mime_type="audio/wav",
        )
        self.account_state = FakeAccountState(
            connected=True,
            quota=SoundCloudQuotaSnapshot(
                rate_limit_remaining=3,
                rate_limit_reset="2026-05-28T10:00:00Z",
                rate_limit_reset_seconds=120,
            ),
        )
        self.planner = SoundCloudPublishPlanner(
            self.track_provider,
            self.release_provider,
            self.media_provider,
            self.publication_lookup,
            self.account_state,
        )

        item = self._plan([13]).items[0]
        self.assertIn(
            SoundCloudPreflightIssueCode.RATE_LIMIT_POTENTIAL.value,
            self._issue_codes(item),
        )

        self.account_state = FakeAccountState(
            connected=True,
            quota=SoundCloudQuotaSnapshot(
                rate_limit_remaining=0,
                rate_limit_reset="2026-05-28T10:00:00Z",
            ),
        )
        self.planner = SoundCloudPublishPlanner(
            self.track_provider,
            self.release_provider,
            self.media_provider,
            self.publication_lookup,
            self.account_state,
        )

        zero_item = self._plan([13]).items[0]
        self.assertEqual(zero_item.status, SoundCloudPlanItemStatus.WARN)
        self.assertIn(
            SoundCloudPreflightIssueCode.RATE_LIMIT_POTENTIAL.value,
            self._issue_codes(zero_item),
        )
        self.assertNotIn(
            SoundCloudPreflightIssueCode.EXPLICIT_QUOTA_EXHAUSTION.value,
            self._issue_codes(zero_item),
        )

    def test_duration_and_file_size_limits_are_blocking(self):
        self.track_provider.snapshots[14] = {
            "track_id": 14,
            "track_title": "Very Long",
            "audio_duration_seconds": AUDIO_DURATION_LIMIT_SECONDS + 1,
        }
        self.media_provider.audio_handles[14] = FakeMediaHandle(
            filename="track.wav",
            source_path="/tmp/long.wav",
            size_bytes=AUDIO_BYTES_LIMIT + 1,
            mime_type="audio/wav",
        )
        item = self._plan([14]).items[0]
        self.assertEqual(item.status, SoundCloudPlanItemStatus.BLOCKED)
        self.assertIn(SoundCloudPreflightIssueCode.LONG_DURATION.value, self._issue_codes(item))
        self.assertIn(SoundCloudPreflightIssueCode.TOO_LARGE_AUDIO.value, self._issue_codes(item))

    def test_fake_service_publication_lookup_updates_do_not_replace_audio(self):
        self.track_provider.snapshots[15] = {"track_id": 15, "track_title": "Update Existing"}
        self.track_provider.snapshots[16] = {"track_id": 16, "track_title": "Create New"}
        self.media_provider.audio_handles[15] = FakeMediaHandle(
            filename="a.wav",
            source_path="/tmp/a.wav",
            size_bytes=100,
            mime_type="audio/wav",
        )
        self.media_provider.audio_handles[16] = FakeMediaHandle(
            filename="b.wav",
            source_path="/tmp/b.wav",
            size_bytes=100,
            mime_type="audio/wav",
        )
        self.publication_lookup.publications[15] = {
            "remote_urn": "soundcloud:tracks:987",
            "track_id": 15,
            "id": 42,
        }

        items = self._plan([15, 16]).items
        update_item = items[0]
        create_item = items[1]

        self.assertEqual(update_item.action, SoundCloudPlanAction.UPDATE)
        self.assertEqual(create_item.action, SoundCloudPlanAction.CREATE)
        self.assertEqual(update_item.remote_urn, "soundcloud:tracks:987")
        self.assertEqual(update_item.remote_numeric_id, 987)
        self.assertIsNone(update_item.metadata.asset_data)
        self.assertFalse(update_item.would_upload_audio)
        self.assertEqual(create_item.metadata.asset_data, "/tmp/b.wav")
        self.assertTrue(create_item.would_upload_audio)

    def test_metadata_conflict_fields_warn_and_missing_quota_warn(self):
        self.track_provider.snapshots[17] = {
            "track_id": 17,
            "track_title": "Conflict Fields",
            "isrc": "NOT_A_VALID_ISRC",
            "license": "cc-by",
            "release_date": "invalid-date",
            "label_name": "One",
        }
        self.release_provider.summaries[17] = {
            "release_titles": ["A", "B"],
            "label_names": ["Label", "Another"],
        }
        self.media_provider.audio_handles[17] = FakeMediaHandle(
            filename="track.wav",
            source_path="/tmp/conflict.wav",
            size_bytes=100,
            mime_type="audio/wav",
        )

        item = self._plan([17]).items[0]
        self.assertEqual(item.status, SoundCloudPlanItemStatus.WARN)
        self.assertIn(SoundCloudPreflightIssueCode.METADATA_CONFLICT.value, self._issue_codes(item))
