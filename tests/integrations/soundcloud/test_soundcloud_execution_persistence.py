import sqlite3
import tempfile
import unittest
from pathlib import Path

from isrc_manager.integrations.soundcloud.client import (
    RICH_METADATA_SYNC_WARNING,
    SoundCloudAPIError,
    SoundCloudRemoteTrack,
    SoundCloudRemoteTrackMetadataSnapshot,
)
from isrc_manager.integrations.soundcloud.execution import SoundCloudPublishExecutor
from isrc_manager.integrations.soundcloud.media import SoundCloudPreparedUploadMedia
from isrc_manager.integrations.soundcloud.models import (
    SoundCloudExecutionItemStatus,
    SoundCloudExecutionStatus,
    SoundCloudOAuthTokenBundle,
    SoundCloudPlanAction,
    SoundCloudPlanItemStatus,
    SoundCloudPublishOptions,
    SoundCloudPublishPlanItem,
    SoundCloudPublishPlanResult,
    SoundCloudTrackMetadataPayload,
)
from isrc_manager.integrations.soundcloud.oauth import SoundCloudOAuthService
from isrc_manager.integrations.soundcloud.persistence import SoundCloudSQLiteRepository
from isrc_manager.integrations.soundcloud.token_storage import SoundCloudTokenStore
from isrc_manager.services.schema import DatabaseSchemaService
from isrc_manager.tasks.models import TaskCancelledError


class FakeSecureBackend:
    available = True

    def __init__(self):
        self.values = {}
        self.fail_writes = False

    def get_password(self, service_name, account_key):
        return self.values.get((service_name, account_key))

    def set_password(self, service_name, account_key, value):
        if self.fail_writes:
            raise RuntimeError("secure store unavailable")
        self.values[(service_name, account_key)] = value

    def delete_password(self, service_name, account_key):
        self.values.pop((service_name, account_key), None)


class FakeOAuthApiClient:
    def __init__(self):
        self.refresh_calls = []
        self.sign_out_calls = []
        self.refresh_response = SoundCloudOAuthTokenBundle(
            access_token="new-access",
            refresh_token="new-refresh",
            expires_at="2099-01-01T00:00:00+00:00",
        )
        self.refresh_error = None

    def exchange_authorization_code(self, **_kwargs):
        return SoundCloudOAuthTokenBundle(
            access_token="access",
            refresh_token="refresh",
            scope="upload",
            expires_at="2099-01-01T00:00:00+00:00",
        )

    def get_me(self, _access_token):
        return {
            "id": 1001,
            "username": "Catalog Artist",
            "permalink_url": "https://soundcloud.com/catalog-artist",
        }

    def refresh_token(self, **kwargs):
        self.refresh_calls.append(kwargs["refresh_token"])
        if self.refresh_error is not None:
            raise self.refresh_error
        return self.refresh_response

    def sign_out(self, access_token):
        self.sign_out_calls.append(access_token)


class FakePublishApiClient:
    def __init__(self):
        self.upload_calls = []
        self.update_calls = []
        self.fail_titles = set()
        self.cancel_titles = set()
        self.rich_warning_titles = set()

    def upload_track(self, *, access_token, metadata, options):
        self.upload_calls.append((access_token, metadata, options))
        if metadata["title"] in self.cancel_titles:
            raise TaskCancelledError("cancelled during upload")
        if metadata["title"] in self.fail_titles:
            raise SoundCloudAPIError(
                "Upload failed Authorization: OAuth secret-token access_token=abc"
            )
        remote_id = 9000 + len(self.upload_calls)
        return SoundCloudRemoteTrack(
            remote_urn=f"soundcloud:tracks:{remote_id}",
            remote_numeric_id=remote_id,
            remote_url=f"https://soundcloud.com/catalog/{remote_id}",
            raw=(
                {"id": remote_id, "rich_metadata_sync_status": RICH_METADATA_SYNC_WARNING}
                if metadata["title"] in self.rich_warning_titles
                else {"id": remote_id}
            ),
        )

    def update_track_metadata(self, *, access_token, remote_numeric_id, metadata, options):
        self.update_calls.append((access_token, remote_numeric_id, metadata, options))
        return SoundCloudRemoteTrack(
            remote_urn=f"soundcloud:tracks:{remote_numeric_id}",
            remote_numeric_id=remote_numeric_id,
            remote_url=f"https://soundcloud.com/catalog/{remote_numeric_id}",
            raw=(
                {"id": remote_numeric_id, "rich_metadata_sync_status": RICH_METADATA_SYNC_WARNING}
                if metadata["title"] in self.rich_warning_titles
                else {"id": remote_numeric_id}
            ),
        )


class FetchingPublishApiClient(FakePublishApiClient):
    def __init__(self):
        super().__init__()
        self.fetch_calls = []
        self.update_returns_url = True

    def fetch_track_metadata(self, *, access_token, remote_track_ref):
        self.fetch_calls.append((access_token, remote_track_ref))
        return SoundCloudRemoteTrackMetadataSnapshot(
            remote_urn=f"soundcloud:tracks:{str(remote_track_ref).rsplit(':', 1)[-1]}",
            remote_numeric_id=int(str(remote_track_ref).rsplit(":", 1)[-1]),
            remote_url=f"https://soundcloud.com/catalog/{str(remote_track_ref).rsplit(':', 1)[-1]}",
            title="Remote title",
            description="Remote description",
            genre="Electronic",
            tag_list="Psybient Dub",
            purchase_url="https://example.invalid/buy",
            label_name="Remote Label",
            release="Remote Release",
            release_date="2026-05-28",
            isrc="NL-C5I-26-00001",
            metadata_artist="Remote Artist",
            publisher_metadata={"contains_music": True},
        )

    def upload_track(self, *, access_token, metadata, options):
        self.upload_calls.append((access_token, metadata, options))
        remote_id = 9100 + len(self.upload_calls)
        return SoundCloudRemoteTrack(
            remote_urn=f"soundcloud:tracks:{remote_id}",
            remote_numeric_id=remote_id,
            remote_url=None,
            raw={"id": remote_id},
        )

    def update_track_metadata(self, *, access_token, remote_numeric_id, metadata, options):
        self.update_calls.append((access_token, remote_numeric_id, metadata, options))
        return SoundCloudRemoteTrack(
            remote_urn=f"soundcloud:tracks:{remote_numeric_id}",
            remote_numeric_id=remote_numeric_id,
            remote_url=(
                f"https://soundcloud.com/catalog/{remote_numeric_id}"
                if self.update_returns_url
                else None
            ),
            raw={"id": remote_numeric_id},
        )


class RefreshFailingPublishApiClient(FakePublishApiClient):
    def __init__(self):
        super().__init__()
        self.fetch_calls = []

    def fetch_track_metadata(self, *, access_token, remote_track_ref):
        self.fetch_calls.append((access_token, remote_track_ref))
        raise SoundCloudAPIError(
            "metadata refresh failed Authorization: Bearer secret-token access_token=abc"
        )


class FakeOAuthTokenService:
    def token_for_account(self, _account_id, **_kwargs):
        return "access-token"


class FailingOAuthTokenService:
    def token_for_account(self, _account_id, **_kwargs):
        raise RuntimeError("token failed access_token=abc Authorization: Bearer secret-token")


class FakeUploadMediaPreparer:
    def __init__(self):
        self.calls = []
        self.prepared: list[SoundCloudPreparedUploadMedia] = []

    def prepare_upload_media(self, track_id, *, include_artwork):
        self.calls.append((track_id, include_artwork))
        temp_dir = tempfile.TemporaryDirectory()
        path = Path(temp_dir.name) / f"track-{track_id}.watermarked.wav"
        path.write_bytes(b"watermarked-wav")
        prepared = SoundCloudPreparedUploadMedia(
            audio_path=path,
            artwork_path=None,
            audio_sha256="prepared-audio-sha",
            _temp_dir=temp_dir,
        )
        self.prepared.append(prepared)
        return prepared


class CancelBeforeSecondItem:
    def __init__(self):
        self.raise_calls = 0

    def is_cancelled(self):
        return self.raise_calls >= 3

    def raise_if_cancelled(self):
        self.raise_calls += 1
        if self.is_cancelled():
            raise TaskCancelledError("publish cancelled")

    def report_progress(self, value=None, maximum=None, message=None):
        pass

    def set_status(self, message):
        pass


def _init_conn():
    conn = sqlite3.connect(":memory:")
    service = DatabaseSchemaService(conn)
    service.init_db()
    service.migrate_schema()
    return conn


def _audio_file(tmpdir: str, name: str = "track.wav") -> str:
    path = Path(tmpdir) / name
    path.write_bytes(b"soundcloud-audio")
    return str(path)


def _plan_item(track_id: int, title: str, audio_path: str | None, *, remote_id=None):
    action = SoundCloudPlanAction.UPDATE if remote_id is not None else SoundCloudPlanAction.CREATE
    return SoundCloudPublishPlanItem(
        track_id=track_id,
        status=SoundCloudPlanItemStatus.READY,
        action=action,
        title=title,
        remote_urn=f"soundcloud:tracks:{remote_id}" if remote_id is not None else None,
        remote_numeric_id=remote_id,
        metadata=SoundCloudTrackMetadataPayload(
            track_id=track_id,
            title=title,
            asset_data=None if remote_id is not None else audio_path,
            genre="electronic",
        ),
        would_upload_audio=remote_id is None,
    )


class SoundCloudExecutionPersistenceTests(unittest.TestCase):
    def test_migration_creates_soundcloud_tables_without_secret_columns(self):
        conn = _init_conn()
        try:
            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            self.assertIn("SoundCloudAccounts", tables)
            self.assertIn("SoundCloudTrackPublications", tables)
            self.assertIn("SoundCloudPublishRuns", tables)
            self.assertIn("SoundCloudPublishRunItems", tables)
            account_columns = {
                row[1] for row in conn.execute("PRAGMA table_info(SoundCloudAccounts)")
            }
            publication_columns = {
                row[1] for row in conn.execute("PRAGMA table_info(SoundCloudTrackPublications)")
            }
            forbidden = {"access_token", "refresh_token", "client_secret", "authorization_header"}
            self.assertFalse(forbidden & account_columns)
            self.assertIn("track_id", publication_columns)
            self.assertIn("remote_urn", publication_columns)
            self.assertIn("soundcloud_url", publication_columns)
        finally:
            conn.close()

    def test_migration_rollback_leaves_version_and_tables_unchanged(self):
        class FailingSchemaService(DatabaseSchemaService):
            def _ensure_soundcloud_tables(self):
                super()._ensure_soundcloud_tables()
                raise RuntimeError("boom")

        conn = _init_conn()
        try:
            conn.execute("DROP TABLE SoundCloudPublishRunItems")
            conn.execute("DROP TABLE SoundCloudPublishRuns")
            conn.execute("DROP TABLE SoundCloudTrackPublications")
            conn.execute("DROP TABLE SoundCloudAccounts")
            conn.execute("PRAGMA user_version = 42")
            conn.commit()
            service = FailingSchemaService(conn)

            with self.assertRaises(RuntimeError):
                service.migrate_schema()

            self.assertEqual(service.get_db_version(), 42)
            self.assertIsNone(
                conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name='SoundCloudAccounts'"
                ).fetchone()
            )
        finally:
            conn.close()

    def test_stale_in_progress_runs_are_recovered_as_failed(self):
        conn = _init_conn()
        try:
            repo = SoundCloudSQLiteRepository(conn)
            account_id = repo.upsert_connected_account(
                account_key="soundcloud:user:stale",
                token_store_key="soundcloud:user:stale",
                token_kind=SoundCloudTokenStore().save_bundle(
                    "soundcloud:user:stale",
                    SoundCloudOAuthTokenBundle(access_token="a", refresh_token="r"),
                ),
                account_payload={"id": 88, "username": "Publisher"},
                scope="upload",
                token_expires_at=None,
            )
            item = _plan_item(1, "Stale Upload", "/tmp/stale.wav")
            plan = SoundCloudPublishPlanResult(
                track_ids=(1,),
                items=(item,),
                options=SoundCloudPublishOptions(),
            )
            run_id = repo.create_publish_run(account_id, plan)
            item_id = repo.create_run_item(run_id, item)
            repo.mark_run_status(run_id, SoundCloudExecutionStatus.IN_PROGRESS)
            conn.execute(
                """
                UPDATE SoundCloudPublishRuns
                SET updated_at=datetime('now', '-2 hours')
                WHERE id=?
                """,
                (run_id,),
            )
            conn.execute(
                """
                UPDATE SoundCloudPublishRunItems
                SET status=?, updated_at=datetime('now', '-2 hours')
                WHERE id=?
                """,
                (SoundCloudExecutionItemStatus.IN_PROGRESS.value, item_id),
            )
            conn.commit()

            recovered = repo.mark_stale_in_progress_runs_failed(older_than_minutes=30)

            run = conn.execute(
                """
                SELECT status, items_succeeded, items_failed, items_skipped, redacted_error
                FROM SoundCloudPublishRuns
                WHERE id=?
                """,
                (run_id,),
            ).fetchone()
            item_row = conn.execute(
                """
                SELECT status, redacted_error
                FROM SoundCloudPublishRunItems
                WHERE id=?
                """,
                (item_id,),
            ).fetchone()
            self.assertEqual(recovered, 1)
            self.assertEqual(run[0], SoundCloudExecutionStatus.FAILED.value)
            self.assertEqual(run[1], 0)
            self.assertEqual(run[2], 1)
            self.assertEqual(run[3], 0)
            self.assertIn("stale in-progress recovery", run[4])
            self.assertEqual(item_row[0], SoundCloudExecutionItemStatus.FAILED.value)
            self.assertIn("stale in-progress recovery", item_row[1])
        finally:
            conn.close()

    def test_repository_account_publication_lookup_and_history_helpers(self):
        conn = _init_conn()
        try:
            repo = SoundCloudSQLiteRepository(conn)

            self.assertIsNone(repo.active_account())
            self.assertIsNone(repo.account_by_id(9999))
            account_id = repo.upsert_connected_account(
                account_key="soundcloud:user:lookup",
                token_store_key="soundcloud:user:lookup",
                token_kind=SoundCloudTokenStore().save_bundle(
                    "soundcloud:user:lookup",
                    SoundCloudOAuthTokenBundle(access_token="a", refresh_token="r"),
                ),
                account_payload={
                    "id": "555",
                    "username": "Lookup Artist",
                    "permalink_url": "https://soundcloud.com/lookup",
                    "avatar_url": "https://img.invalid/avatar.png",
                },
                scope="upload",
                token_expires_at="2099-01-01T00:00:00+00:00",
            )

            active = repo.active_account()
            by_id = repo.account_by_id(account_id)

            self.assertIsNotNone(active)
            self.assertIsNotNone(by_id)
            assert active is not None
            assert by_id is not None
            self.assertEqual(active.username, "Lookup Artist")
            self.assertEqual(by_id.soundcloud_user_id, "555")

            repo.record_token_refresh(
                account_id,
                token_kind=SoundCloudTokenStore().save_bundle(
                    "soundcloud:user:lookup",
                    SoundCloudOAuthTokenBundle(access_token="new", refresh_token="new-r"),
                ),
                scope="upload write",
                token_expires_at="2100-01-01T00:00:00+00:00",
            )
            repo.mark_disconnected(
                account_id,
                error="disconnect failed Authorization: OAuth secret-token access_token=abc",
            )
            self.assertIsNone(repo.active_account())
            last_error = conn.execute(
                "SELECT last_error FROM SoundCloudAccounts WHERE id=?",
                (account_id,),
            ).fetchone()[0]
            self.assertIn("access_token=***", last_error)
            self.assertNotIn("secret-token", last_error)

            account_id = repo.upsert_connected_account(
                account_key="soundcloud:user:lookup",
                token_store_key="soundcloud:user:lookup",
                token_kind=SoundCloudTokenStore().save_bundle(
                    "soundcloud:user:lookup",
                    SoundCloudOAuthTokenBundle(access_token="a2", refresh_token="r2"),
                ),
                account_payload={"id": "555", "username": "Lookup Artist"},
                scope="upload",
                token_expires_at=None,
            )
            publication_id = repo.link_publication(
                account_id=account_id,
                track_id=42,
                remote_urn="soundcloud:tracks:4242",
                remote_numeric_id=4242,
                remote_url="https://soundcloud.com/lookup/old",
            )
            updated_publication_id = repo.link_publication(
                account_id=account_id,
                track_id=42,
                remote_urn="soundcloud:tracks:4243",
                remote_numeric_id=4243,
                remote_url="https://soundcloud.com/lookup/new",
            )

            any_account_publication = repo.find_publication(42)
            account_publication = repo.find_publication(42, account_id=account_id)

            self.assertEqual(updated_publication_id, publication_id)
            assert any_account_publication is not None
            assert account_publication is not None
            self.assertEqual(any_account_publication["remote_urn"], "soundcloud:tracks:4243")
            self.assertEqual(
                account_publication["soundcloud_url"], "https://soundcloud.com/lookup/new"
            )

            plan = SoundCloudPublishPlanResult(
                track_ids=(42,),
                items=(_plan_item(42, "History Row", "/tmp/history.wav"),),
                options=SoundCloudPublishOptions(),
            )
            repo.create_publish_run(account_id, plan)
            runs = repo.list_publish_runs(limit=9999)

            self.assertEqual(runs[0]["account_id"], account_id)
            self.assertEqual(runs[0]["items_total"], 1)
        finally:
            conn.close()

    def test_account_connection_refresh_and_disconnect_store_no_sqlite_secrets(self):
        conn = _init_conn()
        try:
            backend = FakeSecureBackend()
            token_store = SoundCloudTokenStore(persistent_backend=backend)
            repo = SoundCloudSQLiteRepository(conn)
            api = FakeOAuthApiClient()
            service = SoundCloudOAuthService(
                client=api,
                token_store=token_store,
                repository=repo,
            )

            result = service.complete_authorization_callback(
                callback_url="isrc://soundcloud/callback?code=auth-code&state=state-1",
                expected_state="state-1",
                client_id="client",
                client_secret="secret",
                redirect_uri="isrc://soundcloud/callback",
                code_verifier="verifier",
            )
            service.refresh_account(result.account_id, client_id="client", client_secret="secret")
            service.disconnect_account(result.account_id)
            conn.commit()

            row_text = "\n".join(
                str(row) for row in conn.execute("SELECT * FROM SoundCloudAccounts")
            )
            self.assertNotIn("access", row_text)
            self.assertNotIn("refresh", row_text)
            self.assertNotIn("secret", row_text)
            self.assertEqual(api.refresh_calls, ["refresh"])
            self.assertEqual(api.sign_out_calls, ["new-access"])
            self.assertIsNone(token_store.load_bundle(result.account_key))
        finally:
            conn.close()

    def test_refresh_secure_store_failure_prevents_sqlite_state_update(self):
        conn = _init_conn()
        try:
            backend = FakeSecureBackend()
            token_store = SoundCloudTokenStore(persistent_backend=backend)
            repo = SoundCloudSQLiteRepository(conn)
            api = FakeOAuthApiClient()
            service = SoundCloudOAuthService(client=api, token_store=token_store, repository=repo)
            token_store.save_bundle(
                "soundcloud:user:42",
                SoundCloudOAuthTokenBundle(access_token="old-access", refresh_token="old-refresh"),
            )
            account_id = repo.upsert_connected_account(
                account_key="soundcloud:user:42",
                token_store_key="soundcloud:user:42",
                token_kind=token_store.save_bundle(
                    "soundcloud:user:42",
                    SoundCloudOAuthTokenBundle(
                        access_token="old-access",
                        refresh_token="old-refresh",
                    ),
                ),
                account_payload={"id": 42, "username": "Store Failure"},
                scope="upload",
                token_expires_at="2026-01-01T00:00:00+00:00",
            )
            conn.commit()
            backend.fail_writes = True

            with self.assertRaises(Exception):
                service.refresh_account(account_id, client_id="client", client_secret="secret")

            row = conn.execute(
                "SELECT last_token_refresh_at, token_expires_at FROM SoundCloudAccounts WHERE id=?",
                (account_id,),
            ).fetchone()
            self.assertIsNone(row[0])
            self.assertEqual(row[1], "2026-01-01T00:00:00+00:00")
        finally:
            conn.close()

    def test_refresh_failure_does_not_retry_stale_token(self):
        conn = _init_conn()
        try:
            token_store = SoundCloudTokenStore()
            repo = SoundCloudSQLiteRepository(conn)
            api = FakeOAuthApiClient()
            api.refresh_error = SoundCloudAPIError("refresh failed", status_code=401)
            service = SoundCloudOAuthService(client=api, token_store=token_store, repository=repo)
            token_store.save_bundle(
                "soundcloud:user:77",
                SoundCloudOAuthTokenBundle(access_token="old", refresh_token="stale-refresh"),
            )
            account_id = repo.upsert_connected_account(
                account_key="soundcloud:user:77",
                token_store_key="soundcloud:user:77",
                token_kind=token_store.save_bundle(
                    "soundcloud:user:77",
                    SoundCloudOAuthTokenBundle(access_token="old", refresh_token="stale-refresh"),
                ),
                account_payload={"id": 77, "username": "Stale"},
                scope=None,
                token_expires_at=None,
            )

            with self.assertRaises(SoundCloudAPIError):
                service.refresh_account(account_id, client_id="client", client_secret="secret")

            self.assertEqual(api.refresh_calls, ["stale-refresh"])
        finally:
            conn.close()

    def test_blocked_skip_missing_media_and_unlinked_update_paths_are_persisted(self):
        conn = _init_conn()
        try:
            repo = SoundCloudSQLiteRepository(conn)
            account_id = repo.upsert_connected_account(
                account_key="soundcloud:user:edge-actions",
                token_store_key="soundcloud:user:edge-actions",
                token_kind=SoundCloudTokenStore().save_bundle(
                    "soundcloud:user:edge-actions",
                    SoundCloudOAuthTokenBundle(access_token="a", refresh_token="r"),
                ),
                account_payload={"id": 15, "username": "Publisher"},
                scope="upload",
                token_expires_at=None,
            )
            blocked = SoundCloudPublishPlanItem(
                track_id=1,
                status=SoundCloudPlanItemStatus.BLOCKED,
                action=SoundCloudPlanAction.CREATE,
                title="Blocked",
                metadata=None,
                would_upload_audio=False,
            )
            skip = SoundCloudPublishPlanItem(
                track_id=2,
                status=SoundCloudPlanItemStatus.READY,
                action=SoundCloudPlanAction.SKIP,
                title="Already Current",
                metadata=SoundCloudTrackMetadataPayload(
                    track_id=2, title="Already Current", asset_data=None
                ),
                would_upload_audio=False,
            )
            missing_preparer = _plan_item(3, "Needs Watermark", "/tmp/source.wav")
            unlinked_update = SoundCloudPublishPlanItem(
                track_id=4,
                status=SoundCloudPlanItemStatus.READY,
                action=SoundCloudPlanAction.UPDATE,
                title="Unlinked Update",
                remote_urn=None,
                remote_numeric_id=None,
                metadata=SoundCloudTrackMetadataPayload(
                    track_id=4, title="Unlinked Update", asset_data=None
                ),
                would_upload_audio=False,
            )
            plan = SoundCloudPublishPlanResult(
                track_ids=(1, 2, 3, 4),
                items=(blocked, skip, missing_preparer, unlinked_update),
                options=SoundCloudPublishOptions(),
            )
            executor = SoundCloudPublishExecutor(
                conn=conn,
                client=FakePublishApiClient(),
                oauth_service=FakeOAuthTokenService(),
                repository=repo,
            )

            result = executor.execute_plan(plan, account_id=account_id)

            self.assertEqual(result.status, SoundCloudExecutionStatus.FAILED)
            self.assertEqual(
                [item.status for item in result.item_results],
                [
                    SoundCloudExecutionItemStatus.SKIPPED,
                    SoundCloudExecutionItemStatus.SKIPPED,
                    SoundCloudExecutionItemStatus.FAILED,
                    SoundCloudExecutionItemStatus.FAILED,
                ],
            )
            rows = conn.execute(
                "SELECT status, operation_message, redacted_error FROM SoundCloudPublishRunItems ORDER BY track_id"
            ).fetchall()
            self.assertEqual(rows[0][1], "Preflight blocked this item.")
            self.assertEqual(rows[1][1], "Publish action is skip.")
            self.assertIn("watermarked WAV media preparer", rows[2][2])
            self.assertIn("no updateable track id", rows[3][2])
        finally:
            conn.close()

    def test_successful_upload_persists_run_item_and_publication(self):
        conn = _init_conn()
        try:
            repo = SoundCloudSQLiteRepository(conn)
            account_id = repo.upsert_connected_account(
                account_key="soundcloud:user:1",
                token_store_key="soundcloud:user:1",
                token_kind=SoundCloudTokenStore().save_bundle(
                    "soundcloud:user:1",
                    SoundCloudOAuthTokenBundle(access_token="a", refresh_token="r"),
                ),
                account_payload={"id": 1, "username": "Publisher"},
                scope="upload",
                token_expires_at=None,
            )
            with tempfile.TemporaryDirectory() as tmpdir:
                item = _plan_item(1, "Upload Me", _audio_file(tmpdir))
                plan = SoundCloudPublishPlanResult(
                    track_ids=(1,),
                    items=(item,),
                    options=SoundCloudPublishOptions(),
                )
                client = FakePublishApiClient()
                media_preparer = FakeUploadMediaPreparer()
                executor = SoundCloudPublishExecutor(
                    conn=conn,
                    client=client,
                    oauth_service=FakeOAuthTokenService(),
                    repository=repo,
                    media_preparer=media_preparer,
                )

                result = executor.execute_plan(plan, account_id=account_id)

            self.assertEqual(result.status, SoundCloudExecutionStatus.COMPLETED)
            self.assertEqual(result.items_succeeded, 1)
            self.assertEqual(client.upload_calls[0][1]["title"], "Upload Me")
            uploaded_asset = Path(str(client.upload_calls[0][1]["asset_data"]))
            self.assertEqual(uploaded_asset.name, "track-1.watermarked.wav")
            self.assertEqual(media_preparer.calls, [(1, False)])
            publication = conn.execute("""
                SELECT remote_urn, soundcloud_url, metadata_hash, audio_hash
                FROM SoundCloudTrackPublications
                """).fetchone()
            self.assertEqual(publication[0], "soundcloud:tracks:9001")
            self.assertEqual(publication[1], "https://soundcloud.com/catalog/9001")
            self.assertTrue(publication[2])
            self.assertTrue(publication[3])
        finally:
            conn.close()

    def test_upload_metadata_refresh_failure_keeps_successful_primary_upload(self):
        conn = _init_conn()
        try:
            repo = SoundCloudSQLiteRepository(conn)
            account_id = repo.upsert_connected_account(
                account_key="soundcloud:user:refresh-failure",
                token_store_key="soundcloud:user:refresh-failure",
                token_kind=SoundCloudTokenStore().save_bundle(
                    "soundcloud:user:refresh-failure",
                    SoundCloudOAuthTokenBundle(access_token="a", refresh_token="r"),
                ),
                account_payload={"id": 16, "username": "Publisher"},
                scope="upload",
                token_expires_at=None,
            )
            with tempfile.TemporaryDirectory() as tmpdir:
                item = _plan_item(1, "Upload With Refresh Failure", _audio_file(tmpdir))
                plan = SoundCloudPublishPlanResult(
                    track_ids=(1,),
                    items=(item,),
                    options=SoundCloudPublishOptions(),
                )
                client = RefreshFailingPublishApiClient()
                executor = SoundCloudPublishExecutor(
                    conn=conn,
                    client=client,
                    oauth_service=FakeOAuthTokenService(),
                    repository=repo,
                    media_preparer=FakeUploadMediaPreparer(),
                )

                result = executor.execute_plan(plan, account_id=account_id)

            self.assertEqual(result.status, SoundCloudExecutionStatus.COMPLETED)
            self.assertEqual(client.fetch_calls, [("access-token", "soundcloud:tracks:9001")])
            self.assertEqual(
                result.item_results[0].remote_url, "https://soundcloud.com/catalog/9001"
            )
            item_error = conn.execute(
                "SELECT redacted_error FROM SoundCloudPublishRunItems"
            ).fetchone()[0]
            self.assertIsNone(item_error)
        finally:
            conn.close()

    def test_upload_refreshes_remote_metadata_url_after_write(self):
        conn = _init_conn()
        try:
            repo = SoundCloudSQLiteRepository(conn)
            account_id = repo.upsert_connected_account(
                account_key="soundcloud:user:fetch-upload",
                token_store_key="soundcloud:user:fetch-upload",
                token_kind=SoundCloudTokenStore().save_bundle(
                    "soundcloud:user:fetch-upload",
                    SoundCloudOAuthTokenBundle(access_token="a", refresh_token="r"),
                ),
                account_payload={"id": 10, "username": "Publisher"},
                scope="upload",
                token_expires_at=None,
            )
            with tempfile.TemporaryDirectory() as tmpdir:
                item = _plan_item(1, "Upload Refresh", _audio_file(tmpdir))
                plan = SoundCloudPublishPlanResult(
                    track_ids=(1,),
                    items=(item,),
                    options=SoundCloudPublishOptions(),
                )
                client = FetchingPublishApiClient()
                executor = SoundCloudPublishExecutor(
                    conn=conn,
                    client=client,
                    oauth_service=FakeOAuthTokenService(),
                    repository=repo,
                    media_preparer=FakeUploadMediaPreparer(),
                )

                result = executor.execute_plan(plan, account_id=account_id)

            self.assertEqual(
                result.item_results[0].remote_url, "https://soundcloud.com/catalog/9101"
            )
            self.assertEqual(client.fetch_calls, [("access-token", "soundcloud:tracks:9101")])
            publication = conn.execute(
                "SELECT soundcloud_url FROM SoundCloudTrackPublications WHERE track_id=1"
            ).fetchone()
            self.assertEqual(publication[0], "https://soundcloud.com/catalog/9101")
        finally:
            conn.close()

    def test_update_fetches_remote_metadata_before_database_metadata_write(self):
        conn = _init_conn()
        try:
            repo = SoundCloudSQLiteRepository(conn)
            account_id = repo.upsert_connected_account(
                account_key="soundcloud:user:fetch-update",
                token_store_key="soundcloud:user:fetch-update",
                token_kind=SoundCloudTokenStore().save_bundle(
                    "soundcloud:user:fetch-update",
                    SoundCloudOAuthTokenBundle(access_token="a", refresh_token="r"),
                ),
                account_payload={"id": 11, "username": "Publisher"},
                scope="upload",
                token_expires_at=None,
            )
            item = _plan_item(1, "Database Metadata", None, remote_id=1234)
            item = SoundCloudPublishPlanItem(
                track_id=item.track_id,
                status=item.status,
                action=item.action,
                title=item.title,
                remote_urn=item.remote_urn,
                remote_numeric_id=11,
                metadata=SoundCloudTrackMetadataPayload(
                    track_id=1,
                    title="Database Metadata",
                    asset_data=None,
                    description="Description from DB",
                    metadata_artist="Artist from DB",
                    publisher="Publisher from DB",
                    composer="Composer from DB",
                    album_title="Album from DB",
                    upc_or_ean="1234567890123",
                    iswc="T-123.456.789-0",
                    p_line="℗ 2026 : Owner Company",
                    contains_music=True,
                    contains_explicit=False,
                ),
                issues=item.issues,
                would_upload_audio=False,
            )
            plan = SoundCloudPublishPlanResult(
                track_ids=(1,),
                items=(item,),
                options=SoundCloudPublishOptions(tag_list="Psybient, Dub"),
            )
            client = FetchingPublishApiClient()
            client.update_returns_url = False
            executor = SoundCloudPublishExecutor(
                conn=conn,
                client=client,
                oauth_service=FakeOAuthTokenService(),
                repository=repo,
            )

            result = executor.execute_plan(plan, account_id=account_id)

            self.assertEqual(client.fetch_calls, [("access-token", "soundcloud:tracks:1234")])
            self.assertEqual(client.update_calls[0][1], 1234)
            self.assertEqual(client.update_calls[0][2]["metadata_artist"], "Artist from DB")
            self.assertEqual(client.update_calls[0][2]["publisher"], "Publisher from DB")
            self.assertEqual(client.update_calls[0][2]["composer"], "Composer from DB")
            self.assertEqual(client.update_calls[0][2]["album_title"], "Album from DB")
            self.assertEqual(client.update_calls[0][2]["upc_or_ean"], "1234567890123")
            self.assertEqual(client.update_calls[0][2]["iswc"], "T-123.456.789-0")
            self.assertEqual(client.update_calls[0][2]["p_line"], "℗ 2026 : Owner Company")
            self.assertIs(client.update_calls[0][2]["contains_music"], True)
            self.assertIs(client.update_calls[0][2]["contains_explicit"], False)
            self.assertEqual(
                result.item_results[0].remote_url, "https://soundcloud.com/catalog/1234"
            )
            publication = conn.execute("""
                SELECT remote_urn, soundcloud_url, metadata_hash
                FROM SoundCloudTrackPublications
                WHERE track_id=1
                """).fetchone()
            self.assertEqual(publication[0], "soundcloud:tracks:1234")
            self.assertEqual(publication[1], "https://soundcloud.com/catalog/1234")
            self.assertTrue(publication[2])
        finally:
            conn.close()

    def test_rich_metadata_rejection_is_persisted_as_success_warning(self):
        conn = _init_conn()
        try:
            repo = SoundCloudSQLiteRepository(conn)
            account_id = repo.upsert_connected_account(
                account_key="soundcloud:user:rich-warning",
                token_store_key="soundcloud:user:rich-warning",
                token_kind=SoundCloudTokenStore().save_bundle(
                    "soundcloud:user:rich-warning",
                    SoundCloudOAuthTokenBundle(access_token="a", refresh_token="r"),
                ),
                account_payload={"id": 14, "username": "Publisher"},
                scope="upload",
                token_expires_at=None,
            )
            item = _plan_item(1, "Rich Warning", None, remote_id=4321)
            plan = SoundCloudPublishPlanResult(
                track_ids=(1,),
                items=(item,),
                options=SoundCloudPublishOptions(),
            )
            client = FakePublishApiClient()
            client.rich_warning_titles.add("Rich Warning")
            executor = SoundCloudPublishExecutor(
                conn=conn,
                client=client,
                oauth_service=FakeOAuthTokenService(),
                repository=repo,
            )

            result = executor.execute_plan(plan, account_id=account_id)

            self.assertEqual(result.items_succeeded, 1)
            self.assertIn(
                "rich web-editor metadata was rejected",
                result.item_results[0].operation_message or "",
            )
            row = conn.execute(
                "SELECT status, operation_message FROM SoundCloudPublishRunItems"
            ).fetchone()
            self.assertEqual(row[0], SoundCloudExecutionItemStatus.SUCCESS.value)
            self.assertIn("rich web-editor metadata was rejected", row[1])
        finally:
            conn.close()

    def test_top_level_publish_failure_marks_run_and_items_failed(self):
        conn = _init_conn()
        try:
            repo = SoundCloudSQLiteRepository(conn)
            account_id = repo.upsert_connected_account(
                account_key="soundcloud:user:early-failure",
                token_store_key="soundcloud:user:early-failure",
                token_kind=SoundCloudTokenStore().save_bundle(
                    "soundcloud:user:early-failure",
                    SoundCloudOAuthTokenBundle(access_token="a", refresh_token="r"),
                ),
                account_payload={"id": 12, "username": "Publisher"},
                scope="upload",
                token_expires_at=None,
            )
            with tempfile.TemporaryDirectory() as tmpdir:
                item = _plan_item(1, "Upload Me", _audio_file(tmpdir))
                plan = SoundCloudPublishPlanResult(
                    track_ids=(1,),
                    items=(item,),
                    options=SoundCloudPublishOptions(),
                )
                executor = SoundCloudPublishExecutor(
                    conn=conn,
                    client=FakePublishApiClient(),
                    oauth_service=FailingOAuthTokenService(),
                    repository=repo,
                    media_preparer=FakeUploadMediaPreparer(),
                )

                with self.assertRaises(RuntimeError):
                    executor.execute_plan(plan, account_id=account_id)

            run = conn.execute("""
                SELECT status, items_succeeded, items_failed, redacted_error
                FROM SoundCloudPublishRuns
                """).fetchone()
            item_row = conn.execute(
                "SELECT status, redacted_error FROM SoundCloudPublishRunItems"
            ).fetchone()
            stored_text = f"{run!r}\n{item_row!r}"
            self.assertEqual(run[0], SoundCloudExecutionStatus.FAILED.value)
            self.assertEqual(run[1], 0)
            self.assertEqual(run[2], 1)
            self.assertEqual(item_row[0], SoundCloudExecutionItemStatus.FAILED.value)
            self.assertNotIn("access_token=abc", stored_text)
            self.assertNotIn("secret-token", stored_text)
        finally:
            conn.close()

    def test_per_track_failure_isolated_and_error_redacted(self):
        conn = _init_conn()
        try:
            repo = SoundCloudSQLiteRepository(conn)
            account_id = repo.upsert_connected_account(
                account_key="soundcloud:user:2",
                token_store_key="soundcloud:user:2",
                token_kind=SoundCloudTokenStore().save_bundle(
                    "soundcloud:user:2",
                    SoundCloudOAuthTokenBundle(access_token="a", refresh_token="r"),
                ),
                account_payload={"id": 2, "username": "Publisher"},
                scope="upload",
                token_expires_at=None,
            )
            with tempfile.TemporaryDirectory() as tmpdir:
                first = _plan_item(1, "Good", _audio_file(tmpdir, "one.wav"))
                second = _plan_item(2, "Bad", _audio_file(tmpdir, "two.wav"))
                plan = SoundCloudPublishPlanResult(
                    track_ids=(1, 2),
                    items=(first, second),
                    options=SoundCloudPublishOptions(),
                )
                client = FakePublishApiClient()
                client.fail_titles.add("Bad")
                executor = SoundCloudPublishExecutor(
                    conn=conn,
                    client=client,
                    oauth_service=FakeOAuthTokenService(),
                    repository=repo,
                    media_preparer=FakeUploadMediaPreparer(),
                )

                result = executor.execute_plan(plan, account_id=account_id)

            statuses = [
                row[0]
                for row in conn.execute(
                    "SELECT status FROM SoundCloudPublishRunItems ORDER BY id"
                ).fetchall()
            ]
            error_text = "\n".join(
                str(row[0])
                for row in conn.execute(
                    "SELECT redacted_error FROM SoundCloudPublishRunItems WHERE redacted_error IS NOT NULL"
                )
            )
            self.assertEqual(result.status, SoundCloudExecutionStatus.FAILED)
            self.assertEqual(statuses, ["success", "failed"])
            self.assertNotIn("secret-token", error_text)
            self.assertNotIn("access_token=abc", error_text)
        finally:
            conn.close()

    def test_update_uses_metadata_update_without_audio_replacement(self):
        conn = _init_conn()
        try:
            repo = SoundCloudSQLiteRepository(conn)
            account_id = repo.upsert_connected_account(
                account_key="soundcloud:user:3",
                token_store_key="soundcloud:user:3",
                token_kind=SoundCloudTokenStore().save_bundle(
                    "soundcloud:user:3",
                    SoundCloudOAuthTokenBundle(access_token="a", refresh_token="r"),
                ),
                account_payload={"id": 3, "username": "Publisher"},
                scope="upload",
                token_expires_at=None,
            )
            item = _plan_item(10, "Update Only", None, remote_id=1234)
            plan = SoundCloudPublishPlanResult(
                track_ids=(10,),
                items=(item,),
                options=SoundCloudPublishOptions(),
            )
            client = FakePublishApiClient()
            executor = SoundCloudPublishExecutor(
                conn=conn,
                client=client,
                oauth_service=FakeOAuthTokenService(),
                repository=repo,
            )

            result = executor.execute_plan(plan, account_id=account_id)

            self.assertEqual(result.item_results[0].status, SoundCloudExecutionItemStatus.SUCCESS)
            self.assertEqual(len(client.upload_calls), 0)
            self.assertEqual(client.update_calls[0][1], 1234)
            self.assertNotIn("asset_data", client.update_calls[0][2])
        finally:
            conn.close()

    def test_cancellation_before_and_during_item_execution(self):
        conn = _init_conn()
        try:
            repo = SoundCloudSQLiteRepository(conn)
            account_id = repo.upsert_connected_account(
                account_key="soundcloud:user:4",
                token_store_key="soundcloud:user:4",
                token_kind=SoundCloudTokenStore().save_bundle(
                    "soundcloud:user:4",
                    SoundCloudOAuthTokenBundle(access_token="a", refresh_token="r"),
                ),
                account_payload={"id": 4, "username": "Publisher"},
                scope="upload",
                token_expires_at=None,
            )
            with tempfile.TemporaryDirectory() as tmpdir:
                first = _plan_item(1, "First", _audio_file(tmpdir, "one.wav"))
                second = _plan_item(2, "Second", _audio_file(tmpdir, "two.wav"))
                plan = SoundCloudPublishPlanResult(
                    track_ids=(1, 2),
                    items=(first, second),
                    options=SoundCloudPublishOptions(),
                )
                executor = SoundCloudPublishExecutor(
                    conn=conn,
                    client=FakePublishApiClient(),
                    oauth_service=FakeOAuthTokenService(),
                    repository=repo,
                    media_preparer=FakeUploadMediaPreparer(),
                )
                result = executor.execute_plan(
                    plan,
                    account_id=account_id,
                    ctx=CancelBeforeSecondItem(),
                )

                client = FakePublishApiClient()
                client.cancel_titles.add("First")
                executor = SoundCloudPublishExecutor(
                    conn=conn,
                    client=client,
                    oauth_service=FakeOAuthTokenService(),
                    repository=repo,
                    media_preparer=FakeUploadMediaPreparer(),
                )
                result_during = executor.execute_plan(plan, account_id=account_id)

            self.assertEqual(result.status, SoundCloudExecutionStatus.CANCELLED)
            self.assertEqual(result.item_results[0].status, SoundCloudExecutionItemStatus.SUCCESS)
            self.assertEqual(result.item_results[1].status, SoundCloudExecutionItemStatus.CANCELLED)
            self.assertEqual(
                result_during.item_results[0].status,
                SoundCloudExecutionItemStatus.CANCELLED,
            )
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
