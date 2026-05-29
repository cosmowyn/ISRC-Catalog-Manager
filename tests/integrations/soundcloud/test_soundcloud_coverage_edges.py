from __future__ import annotations

import http.client
import io
import threading
import urllib.error
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest

from isrc_manager.integrations.soundcloud import client as sc_client
from isrc_manager.integrations.soundcloud import oauth_capture, token_store
from isrc_manager.integrations.soundcloud.client import (
    SC_TRACK_FIELD_ARTWORK_DATA,
    SC_TRACK_FIELD_ASSET_DATA,
    SC_TRACK_FIELD_BPM,
    SC_TRACK_FIELD_TITLE,
    SoundCloudAPIClient,
    SoundCloudAPIError,
    SoundCloudMalformedResponseError,
    SoundCloudTransportResponse,
    UrllibSoundCloudTransport,
)
from isrc_manager.integrations.soundcloud.models import (
    SoundCloudOAuthTokenBundle,
    SoundCloudPublishOptions,
    SoundCloudTokenKind,
)
from isrc_manager.integrations.soundcloud.oauth import (
    SoundCloudOAuthService,
    build_authorization_url,
    generate_pkce_verifier,
    parse_authorization_callback,
    soundcloud_account_key,
    verify_state,
)
from isrc_manager.integrations.soundcloud.oauth_capture import (
    SoundCloudOAuthCallbackCaptureError,
    SoundCloudOAuthCallbackProvider,
    SoundCloudOAuthCaptureConfig,
)
from isrc_manager.integrations.soundcloud.persistence import SoundCloudAccountRecord
from isrc_manager.integrations.soundcloud.token_store import (
    KeychainSoundCloudTokenStore,
    KeyringSoundCloudTokenStorageBackend,
    SessionOnlySoundCloudTokenStore,
    SoundCloudTokenStorageError,
    SoundCloudTokenStore,
)


@dataclass(slots=True)
class _Backend:
    available: bool = True
    priority: object | None = None
    fail_get: bool = False
    fail_set: bool = False
    fail_delete: bool = False
    values: dict[tuple[str, str], str] = field(default_factory=dict)

    def get_password(self, service_name: str, account_key: str) -> str | None:
        if self.fail_get:
            raise RuntimeError("get failed access_token=secret")
        return self.values.get((service_name, account_key))

    def set_password(self, service_name: str, account_key: str, value: str) -> None:
        if self.fail_set:
            raise RuntimeError("set failed refresh_token=secret")
        self.values[(service_name, account_key)] = value

    def delete_password(self, service_name: str, account_key: str) -> None:
        if self.fail_delete:
            raise RuntimeError("delete failed")
        self.values.pop((service_name, account_key), None)


class _MissingMethods:
    available = True


class _FakeResponse:
    def __init__(
        self,
        *,
        status: int = 200,
        headers: dict[str, str] | None = None,
        body: bytes = b"",
    ) -> None:
        self.status = status
        self.headers = dict(headers or {})
        self._body = body

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self) -> bytes:
        return self._body


class _Transport:
    def __init__(self, responses: list[SoundCloudTransportResponse | Exception]) -> None:
        self.responses = responses
        self.requests: list[tuple[str, str, dict[str, object]]] = []

    def request(self, method, url, **kwargs):
        self.requests.append((method, url, kwargs))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def test_urllib_transport_encodes_payloads_and_redacts_network_failures(tmp_path: Path) -> None:
    upload_path = tmp_path / "audio.wav"
    upload_path.write_bytes(b"wav-data")
    calls: list[tuple[object, object]] = []
    responses = [
        _FakeResponse(
            status=201,
            headers={"Content-Type": "application/json"},
            body=b'{"ok":true}',
        ),
        _FakeResponse(
            headers={"Content-Type": "text/plain"},
            body=b"plain text",
        ),
        _FakeResponse(
            headers={"Content-Type": "application/json"},
            body=b'{"uploaded":true}',
        ),
        urllib.error.HTTPError(
            "https://api.example/too-large",
            413,
            "too large",
            {"Content-Type": "application/json"},
            io.BytesIO(b'{"message":"too large"}'),
        ),
        urllib.error.URLError("offline"),
    ]

    def fake_urlopen(request, *, timeout):
        calls.append((request, timeout))
        response = responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    transport = UrllibSoundCloudTransport()
    with mock.patch("urllib.request.urlopen", side_effect=fake_urlopen):
        form = transport.request(
            "POST",
            "https://api.example/form?existing=1",
            params={"q": "search"},
            data={"field": "value"},
            timeout_seconds=3,
        )
        json_response = transport.request(
            "PUT",
            "https://api.example/json",
            json={"field": "value"},
        )
        multipart = transport.request(
            "POST",
            "https://api.example/upload",
            data={"title": "Track"},
            files={"track[asset_data]": upload_path},
        )
        http_error = transport.request("GET", "https://api.example/too-large")
        with pytest.raises(SoundCloudAPIError):
            transport.request("GET", "https://api.example/offline?code=secret")

    assert form.status_code == 201
    assert form.body == {"ok": True}
    assert json_response.body == "plain text"
    assert multipart.body == {"uploaded": True}
    assert http_error.status_code == 413
    assert http_error.body == {"message": "too large"}
    assert calls[0][0].full_url.endswith("existing=1&q=search")
    assert calls[0][0].data == b"field=value"
    assert calls[1][0].headers["Content-type"] == "application/json"
    assert b"wav-data" in calls[2][0].data
    assert calls[0][1] == 3


def test_client_helper_edges_and_request_field_policies(tmp_path: Path) -> None:
    assert sc_client.is_supported_track_field(SC_TRACK_FIELD_TITLE)
    assert sc_client.unsupported_track_fields(["", SC_TRACK_FIELD_BPM, "track[custom]"]) == [
        "track[bpm]",
        "track[custom]",
    ]
    assert sc_client.redact_headers(None) == {}
    redacted_headers = sc_client.redact_headers(
        {
            "Authorization": "OAuth secret-token",
            "Cookie": "session=secret",
            "X-Trace": "access_token=secret",
        }
    )
    assert redacted_headers["Authorization"] == "Authorization: OAuth ***"
    assert redacted_headers["Cookie"] == "***"
    assert redacted_headers["X-Trace"] == "access_token=***"
    assert sc_client._url_for_log("https://host/callback?code=secret#frag") == (
        "https://host/callback"
    )
    assert sc_client._coerce_int(object()) is None
    assert sc_client.parse_rate_limit_error(200) is None
    assert sc_client.parse_rate_limit_error(429, body="slow down").message == "slow down"
    assert sc_client.parse_scope_scopes(None) == ""
    assert sc_client.parse_scope_scopes(["upload", "upload", "profile"]) == "profile upload"
    assert sc_client.parse_scope_scopes(" upload ") == "upload"
    assert sc_client._b64url_no_padding(b"\xff").endswith("_w")
    assert sc_client._url_with_params("https://api.example/path", None) == (
        "https://api.example/path"
    )
    assert sc_client._url_with_params("https://api.example/path?x=1", {"y": "2"}).endswith(
        "x=1&y=2"
    )
    assert sc_client._decode_response_body(b"{bad", "application/json") == "{bad"
    assert sc_client._decode_response_body(b"plain", "text/plain") == "plain"
    assert sc_client._file_payload(("cover.png", b"png", "image/png")) == (
        "cover.png",
        b"png",
        "image/png",
    )
    with pytest.raises(SoundCloudAPIError):
        sc_client._file_payload(tmp_path / "missing.wav")
    assert (
        sc_client._message_from_body(
            {"errors": [{"error_message": "nested error"}]},
            "fallback",
        )
        == "nested error"
    )
    assert sc_client._message_from_body("  plain error  ", "fallback") == "plain error"
    with pytest.raises(SoundCloudMalformedResponseError):
        sc_client._require_mapping([], "test")
    assert sc_client._coerce_remote_numeric_id("") is None
    assert sc_client._coerce_remote_numeric_id("bad") is None

    metadata = {
        "title": "Title",
        "asset_data": "/tmp/audio.wav",
        "artwork_data": "",
        "genre": None,
        "license": "all-rights-reserved",
        "metadata_artist": "Artist",
        "publisher": "Publisher",
        "composer": "Composer",
        "release": "Release",
        "album_title": "Album",
        "upc_or_ean": "8720892724656",
        "isrc": "NL-C5I-18-00006",
        "iswc": "T-123.456.789-0",
        "p_line": "℗ 2026 : Publisher",
        "contains_music": True,
        "contains_explicit": False,
    }
    upload_fields = sc_client.build_upload_request_fields(metadata)
    assert upload_fields[SC_TRACK_FIELD_ASSET_DATA] == "/tmp/audio.wav"
    options = SoundCloudPublishOptions(
        tag_list="dub",
        commentable=False,
        reveal_stats=False,
        reveal_comments=True,
        purchase_url="https://example.invalid/buy",
    )
    fields = sc_client.build_track_request_fields(metadata, options, include_asset=False)
    assert SC_TRACK_FIELD_ASSET_DATA not in fields
    assert fields["track[commentable]"] == "false"
    assert fields["track[reveal_comments]"] == "true"
    assert fields["track[purchase_url]"] == "https://example.invalid/buy"
    assert fields["track[metadata_artist]"] == "Artist"
    assert fields["track[publisher_metadata][artist]"] == "Artist"
    assert fields["track[publisher_metadata][publisher]"] == "Publisher"
    assert fields["track[publisher_metadata][writer_composer]"] == "Composer"
    assert fields["track[publisher_metadata][release_title]"] == "Release"
    assert fields["track[publisher_metadata][album_title]"] == "Album"
    assert fields["track[publisher_metadata][upc_or_ean]"] == "8720892724656"
    assert fields["track[publisher_metadata][isrc]"] == "NL-C5I-18-00006"
    assert fields["track[publisher_metadata][iswc]"] == "T-123.456.789-0"
    assert fields["track[publisher_metadata][p_line]"] == "℗ 2026 : Publisher"
    assert fields["track[publisher_metadata][contains_music]"] == "true"
    assert fields["track[publisher_metadata][explicit]"] == "false"
    assert "track[publisher_metadata_attributes][publisher]" not in fields
    json_payload = sc_client.build_track_json_payload(metadata, options)
    assert json_payload["metadata_artist"] == "Artist"
    assert json_payload["publisher_metadata"]["publisher"] == "Publisher"
    assert json_payload["track"]["metadata_artist"] == "Artist"
    assert json_payload["track"]["publisher_metadata"]["artist"] == "Artist"
    assert json_payload["track"]["publisher_metadata"]["publisher"] == "Publisher"
    assert json_payload["track"]["publisher_metadata"]["writer_composer"] == "Composer"
    assert json_payload["track"]["publisher_metadata"]["release_title"] == "Release"
    assert json_payload["track"]["publisher_metadata"]["album_title"] == "Album"
    assert json_payload["track"]["publisher_metadata"]["upc_or_ean"] == "8720892724656"
    assert json_payload["track"]["publisher_metadata"]["isrc"] == "NL-C5I-18-00006"
    assert json_payload["track"]["publisher_metadata"]["iswc"] == "T-123.456.789-0"
    assert json_payload["track"]["publisher_metadata"]["p_line"] == "℗ 2026 : Publisher"
    assert json_payload["track"]["publisher_metadata"]["contains_music"] is True
    assert json_payload["track"]["publisher_metadata"]["explicit"] is False


def test_api_client_upload_update_quota_and_malformed_track_response(tmp_path: Path) -> None:
    audio_path = tmp_path / "audio.wav"
    art_path = tmp_path / "art.png"
    audio_path.write_bytes(b"audio")
    art_path.write_bytes(b"art")
    transport = _Transport(
        [
            SoundCloudTransportResponse(
                status_code=200,
                headers={"RateLimit-Remaining": "44", "Retry-After": "5"},
                body={"upload_limit_remaining": "3", "daily_upload_limit": "9"},
            ),
            SoundCloudTransportResponse(status_code=200, headers={}, body=None),
            SoundCloudTransportResponse(
                status_code=200,
                headers={},
                body={"id": "321", "permalink_url": "https://soundcloud.example/t"},
            ),
            SoundCloudTransportResponse(
                status_code=200,
                headers={},
                body={"urn": "soundcloud:tracks:999", "id": "bad"},
            ),
            SoundCloudTransportResponse(
                status_code=200,
                headers={},
                body={
                    "urn": "soundcloud:tracks:1001",
                    "id": 1001,
                    "permalink_url": "https://soundcloud.example/updated",
                },
            ),
            SoundCloudTransportResponse(
                status_code=200,
                headers={},
                body={
                    "urn": "soundcloud:tracks:1001",
                    "id": 1001,
                    "permalink_url": "https://soundcloud.example/updated-rich",
                },
            ),
            SoundCloudTransportResponse(status_code=200, headers={}, body={}),
        ]
    )
    api = SoundCloudAPIClient(
        transport=transport,
        api_base_url="https://api.test",
        api_v2_base_url="https://api-v2.test",
    )

    quota = api.get_quota_snapshot("access")
    api.sign_out("access")
    uploaded = api.upload_track(
        access_token="access",
        metadata={"title": "Track", "asset_data": str(audio_path), "artwork_data": str(art_path)},
        options=SoundCloudPublishOptions(),
    )
    updated = api.update_track_metadata(
        access_token="access",
        remote_numeric_id=999,
        metadata={"title": "Track", "artwork_data": str(art_path)},
        options=SoundCloudPublishOptions(),
    )
    json_updated = api.update_track_metadata(
        access_token="access",
        remote_numeric_id=1001,
        metadata={
            "title": "JSON Track",
            "metadata_artist": "Artist",
            "publisher": "Publisher",
            "composer": "Composer",
            "release": "Release",
            "album_title": "Album",
            "upc_or_ean": "8720892724656",
            "isrc": "NL-C5I-18-00006",
            "iswc": "T-123.456.789-0",
            "p_line": "℗ 2026 : Publisher",
            "contains_music": True,
            "contains_explicit": False,
        },
        options=SoundCloudPublishOptions(tag_list="Deep Space"),
    )
    with pytest.raises(SoundCloudMalformedResponseError):
        api.update_track_metadata(
            access_token="access",
            remote_numeric_id=1000,
            metadata={"title": "Broken"},
            options=SoundCloudPublishOptions(),
        )
    with pytest.raises(ValueError):
        api.upload_track(
            access_token="access",
            metadata={"title": "Missing asset"},
            options=SoundCloudPublishOptions(),
        )

    assert quota.daily_remaining_uploads == 3
    assert quota.rate_limit_remaining == 44
    assert quota.rate_limit_reset_seconds == 5
    assert uploaded.remote_urn == "soundcloud:tracks:321"
    assert uploaded.remote_numeric_id == 321
    assert updated.remote_urn == "soundcloud:tracks:999"
    assert updated.remote_numeric_id is None
    assert json_updated.remote_urn == "soundcloud:tracks:1001"
    assert json_updated.remote_numeric_id == 1001
    assert json_updated.remote_url == "https://soundcloud.example/updated-rich"
    assert transport.requests[2][2]["files"][SC_TRACK_FIELD_ARTWORK_DATA] == str(art_path)
    assert transport.requests[4][2]["json"]["track"]["metadata_artist"] == "Artist"
    assert transport.requests[4][2]["json"]["metadata_artist"] == "Artist"
    assert transport.requests[4][2]["json"]["publisher_metadata"]["writer_composer"] == "Composer"
    assert transport.requests[4][2]["json"]["track"]["publisher_metadata"] == {
        "artist": "Artist",
        "publisher": "Publisher",
        "writer_composer": "Composer",
        "release_title": "Release",
        "album_title": "Album",
        "upc_or_ean": "8720892724656",
        "isrc": "NL-C5I-18-00006",
        "iswc": "T-123.456.789-0",
        "p_line": "℗ 2026 : Publisher",
        "contains_music": True,
        "explicit": False,
    }
    assert transport.requests[5][1] == "https://api-v2.test/tracks/soundcloud:tracks:1001"
    assert transport.requests[5][2]["params"] is None
    assert "track" not in transport.requests[5][2]["json"]
    assert transport.requests[5][2]["json"]["publisher_metadata"]["publisher"] == "Publisher"


def test_api_client_upload_syncs_rich_metadata_after_create(tmp_path: Path) -> None:
    audio_path = tmp_path / "audio.wav"
    audio_path.write_bytes(b"audio")
    transport = _Transport(
        [
            SoundCloudTransportResponse(
                status_code=201,
                headers={},
                body={"id": "777", "urn": "soundcloud:tracks:777"},
            ),
            SoundCloudTransportResponse(
                status_code=200,
                headers={},
                body={
                    "id": 777,
                    "urn": "soundcloud:tracks:777",
                    "permalink_url": "https://soundcloud.example/rich",
                },
            ),
        ]
    )
    api = SoundCloudAPIClient(
        transport=transport,
        api_base_url="https://api.test",
        api_v2_base_url="https://api-v2.test",
    )

    uploaded = api.upload_track(
        access_token="access",
        metadata={
            "title": "Rich Upload",
            "asset_data": str(audio_path),
            "metadata_artist": "Artist",
            "publisher": "Publisher",
            "composer": "Composer",
            "album_title": "Album",
            "upc_or_ean": "8720892724656",
            "p_line": "℗ 2026 : Publisher",
            "contains_music": True,
        },
        options=SoundCloudPublishOptions(),
    )

    assert uploaded.remote_url == "https://soundcloud.example/rich"
    assert transport.requests[0][0] == "POST"
    assert transport.requests[0][2]["files"][SC_TRACK_FIELD_ASSET_DATA] == str(audio_path)
    assert transport.requests[1][0] == "PUT"
    assert transport.requests[1][1] == "https://api-v2.test/tracks/soundcloud:tracks:777"
    assert transport.requests[1][2]["params"] is None
    assert SC_TRACK_FIELD_ASSET_DATA not in transport.requests[1][2]["json"]
    assert transport.requests[1][2]["json"]["publisher_metadata"] == {
        "artist": "Artist",
        "publisher": "Publisher",
        "writer_composer": "Composer",
        "album_title": "Album",
        "upc_or_ean": "8720892724656",
        "p_line": "℗ 2026 : Publisher",
        "contains_music": True,
    }


def test_api_client_rich_metadata_sync_failure_keeps_primary_upload(tmp_path: Path) -> None:
    audio_path = tmp_path / "audio.wav"
    audio_path.write_bytes(b"audio")
    transport = _Transport(
        [
            SoundCloudTransportResponse(
                status_code=201,
                headers={},
                body={
                    "id": "888",
                    "urn": "soundcloud:tracks:888",
                    "permalink_url": "https://soundcloud.example/primary",
                },
            ),
            SoundCloudTransportResponse(status_code=403, headers={}, body={"message": "denied"}),
        ]
    )
    api = SoundCloudAPIClient(
        transport=transport,
        api_base_url="https://api.test",
        api_v2_base_url="https://api-v2.test",
    )

    uploaded = api.upload_track(
        access_token="access",
        metadata={
            "title": "Rich Upload",
            "asset_data": str(audio_path),
            "publisher": "Publisher",
        },
        options=SoundCloudPublishOptions(),
    )

    assert uploaded.remote_url == "https://soundcloud.example/primary"
    assert uploaded.raw["rich_metadata_sync_status"] == sc_client.RICH_METADATA_SYNC_WARNING
    assert "denied" in uploaded.raw["rich_metadata_sync_error"]
    assert transport.requests[1][1] == "https://api-v2.test/tracks/soundcloud:tracks:888"


def test_api_client_fetches_remote_track_metadata_snapshot() -> None:
    transport = _Transport(
        [
            SoundCloudTransportResponse(
                status_code=200,
                headers={},
                body={
                    "urn": "soundcloud:tracks:55",
                    "id": "55",
                    "permalink_url": "https://soundcloud.com/catalog/track",
                    "title": "Remote Title",
                    "description": "Remote Description",
                    "genre": "Electronic",
                    "tag_list": "Psybient Dub",
                    "purchase_url": "https://example.invalid/buy",
                    "label_name": "Label",
                    "release": "Release",
                    "release_date": "2026-05-28",
                    "isrc": "NL-C5I-26-00001",
                    "metadata_artist": "Artist",
                    "publisher_metadata": {"contains_music": True},
                },
            ),
            SoundCloudTransportResponse(
                status_code=200,
                headers={},
                body={
                    "id": "56",
                    "permalink_url": "https://soundcloud.com/catalog/resolved",
                    "title": "Resolved Title",
                },
            ),
            SoundCloudTransportResponse(
                status_code=200,
                headers={},
                body={
                    "collection": [
                        {
                            "id": "57",
                            "urn": "soundcloud:tracks:57",
                            "permalink_url": "https://soundcloud.com/catalog/listed",
                            "title": "Listed Title",
                            "genre": "Ambient",
                            "created_at": "2026-05-28",
                            "duration": "1234",
                        }
                    ]
                },
            ),
            SoundCloudTransportResponse(status_code=200, headers={}, body={}),
            SoundCloudTransportResponse(
                status_code=200,
                headers={},
                body={"collection": {}},
            ),
        ]
    )
    api = SoundCloudAPIClient(transport=transport, api_base_url="https://api.test")

    snapshot = api.fetch_track_metadata(
        access_token="access",
        remote_track_ref="soundcloud:tracks:55",
    )
    resolved = api.resolve_track_url(
        access_token="access",
        track_url="https://soundcloud.com/catalog/resolved",
    )
    listed = api.list_my_tracks(access_token="access", limit=500)
    with pytest.raises(SoundCloudMalformedResponseError):
        api.fetch_track_metadata(access_token="access", remote_track_ref=56)
    with pytest.raises(SoundCloudMalformedResponseError):
        api.list_my_tracks(access_token="access")
    with pytest.raises(ValueError):
        api.fetch_track_metadata(access_token="access", remote_track_ref="")
    with pytest.raises(ValueError):
        api.resolve_track_url(access_token="access", track_url="not a url")

    assert snapshot.remote_urn == "soundcloud:tracks:55"
    assert snapshot.remote_numeric_id == 55
    assert snapshot.remote_url == "https://soundcloud.com/catalog/track"
    assert snapshot.description == "Remote Description"
    assert snapshot.tag_list == "Psybient Dub"
    assert snapshot.metadata_artist == "Artist"
    assert snapshot.publisher_metadata == {"contains_music": True}
    assert transport.requests[0][1].endswith("/tracks/soundcloud:tracks:55")
    assert resolved.remote_urn == "soundcloud:tracks:56"
    assert resolved.remote_url == "https://soundcloud.com/catalog/resolved"
    assert transport.requests[1][1].endswith("/resolve")
    assert transport.requests[1][2]["params"]["url"] == "https://soundcloud.com/catalog/resolved"
    assert listed[0].remote_urn == "soundcloud:tracks:57"
    assert listed[0].duration_ms == 1234
    assert transport.requests[2][1].endswith("/me/tracks")
    assert transport.requests[2][2]["params"]["limit"] == 200


def test_oauth_helper_and_service_error_edges() -> None:
    with pytest.raises(ValueError):
        generate_pkce_verifier(42)
    with pytest.raises(ValueError):
        generate_pkce_verifier(129)
    with pytest.raises(ValueError):
        verify_state("", "")
    with pytest.raises(ValueError):
        parse_authorization_callback("https://example.invalid/callback")
    assert "scope=upload" in build_authorization_url(
        "https://soundcloud.example/connect",
        client_id="client",
        redirect_uri="isrc://callback",
        scopes=" upload ",
        code_challenge="challenge",
        state="state",
    )
    assert soundcloud_account_key(SimpleNamespace(id="", permalink="artist")) == (
        "soundcloud:permalink:artist"
    )
    with pytest.raises(ValueError):
        soundcloud_account_key({})

    class _Client:
        def exchange_authorization_code(self, **_kwargs):
            return SoundCloudOAuthTokenBundle(access_token="access", refresh_token="refresh")

        def get_me(self, _access_token):
            return {"id": "42", "username": "Artist"}

    class _FailingStore(SessionOnlySoundCloudTokenStore):
        def save_bundle(self, account_key, bundle):
            del account_key, bundle
            raise RuntimeError("failed client_secret=secret")

    service = SoundCloudOAuthService(
        client=_Client(),
        token_store=_FailingStore(),
        repository=SimpleNamespace(upsert_connected_account=lambda **_kwargs: 1),
    )
    with pytest.raises(ValueError) as auth_error:
        service.complete_authorization_callback(
            callback_url="isrc://callback?error=access_denied&error_description=code=secret&state=s",
            expected_state="s",
            client_id="client",
            client_secret="secret",
            redirect_uri="isrc://callback",
            code_verifier="verifier",
        )
    assert "code=secret" not in str(auth_error.value)
    with pytest.raises(RuntimeError):
        service.complete_authorization_callback(
            callback_url="isrc://callback?code=auth&state=s",
            expected_state="s",
            client_id="client",
            client_secret="secret",
            redirect_uri="isrc://callback",
            code_verifier="verifier",
        )


def test_oauth_token_for_account_refresh_and_disconnect_edges() -> None:
    account = SoundCloudAccountRecord(
        id=5,
        account_key="soundcloud:user:5",
        token_store_key="soundcloud:user:5",
        token_kind=SoundCloudTokenKind.SESSION,
        connection_status="connected",
        username="Artist",
    )

    class _Repo:
        def __init__(self) -> None:
            self.account = account
            self.refreshes: list[tuple[int, SoundCloudTokenKind, str | None]] = []
            self.disconnects: list[tuple[int, str | None]] = []

        def account_by_id(self, _account_id):
            return self.account

        def record_token_refresh(self, account_id, *, token_kind, scope, token_expires_at):
            del scope
            self.refreshes.append((account_id, token_kind, token_expires_at))

        def mark_disconnected(self, account_id, *, error=None):
            self.disconnects.append((account_id, error))

    class _Client:
        def __init__(self) -> None:
            self.sign_out_error = RuntimeError("remote failed Authorization: Bearer secret")

        def refresh_token(self, **_kwargs):
            return SoundCloudOAuthTokenBundle(
                access_token="new-access",
                refresh_token="new-refresh",
                expires_at="2099-01-01T00:00:00+00:00",
            )

        def sign_out(self, _access_token):
            raise self.sign_out_error

    repo = _Repo()
    store = SessionOnlySoundCloudTokenStore()
    store.save_bundle(
        account.token_store_key,
        SoundCloudOAuthTokenBundle(
            access_token="old-access",
            refresh_token="old-refresh",
            expires_at="2000-01-01T00:00:00+00:00",
        ),
    )
    service = SoundCloudOAuthService(client=_Client(), token_store=store, repository=repo)

    with pytest.raises(ValueError):
        service.token_for_account(account.id)
    assert service.token_for_account(account.id, client_id="client", client_secret="secret") == (
        "new-access"
    )
    assert repo.refreshes[0][0] == account.id

    repo.account = None
    with pytest.raises(ValueError):
        service.token_for_account(account.id)
    service.disconnect_account(account.id)
    assert repo.disconnects == []

    repo.account = account
    service.disconnect_account(account.id)
    assert store.load_bundle(account.token_store_key) is None
    assert "secret" not in str(repo.disconnects[-1][1])


def test_oauth_capture_loopback_prompt_and_redaction(monkeypatch) -> None:
    assert oauth_capture._is_loopback_redirect("http://127.0.0.1:9876/callback")
    assert not oauth_capture._is_loopback_redirect("isrc://soundcloud/callback")
    provider = SoundCloudOAuthCallbackProvider(
        config=SoundCloudOAuthCaptureConfig(timeout_seconds=0.01)
    )
    opened: list[str] = []
    monkeypatch.setattr(oauth_capture.webbrowser, "open", lambda url: opened.append(url))
    monkeypatch.setattr(provider, "_capture_loopback", lambda redirect_uri: redirect_uri)
    assert (
        provider.capture(
            auth_url="https://soundcloud.example/connect",
            expected_state="state",
            redirect_uri="http://127.0.0.1:9876/callback",
        )
        == "http://127.0.0.1:9876/callback"
    )
    monkeypatch.setattr(provider, "_prompt_hidden_callback", lambda: "isrc://callback?code=x")
    assert (
        provider.capture(
            auth_url="https://soundcloud.example/connect2",
            expected_state="state",
            redirect_uri="isrc://soundcloud/callback",
        )
        == "isrc://callback?code=x"
    )
    assert opened == ["https://soundcloud.example/connect", "https://soundcloud.example/connect2"]
    prompt_provider = SoundCloudOAuthCallbackProvider(
        config=SoundCloudOAuthCaptureConfig(timeout_seconds=0.01)
    )
    monkeypatch.setattr(
        oauth_capture.QInputDialog,
        "getText",
        lambda *_args, **_kwargs: ("isrc://callback?code=secret", True),
    )
    assert prompt_provider._prompt_hidden_callback().endswith("code=secret")
    monkeypatch.setattr(
        oauth_capture.QInputDialog,
        "getText",
        lambda *_args, **_kwargs: ("", False),
    )
    with pytest.raises(SoundCloudOAuthCallbackCaptureError):
        prompt_provider._prompt_hidden_callback()
    assert "code=***" in oauth_capture.redacted_callback_error(
        RuntimeError("callback failed code=secret")
    )

    class _TimeoutServer:
        def __init__(self, _address, _redirect_uri):
            self.callback_url = None
            self.timeout = None

        def handle_request(self):
            return None

        def server_close(self):
            return None

    monkeypatch.setattr(oauth_capture, "_LoopbackHTTPServer", _TimeoutServer)
    timeout_provider = SoundCloudOAuthCallbackProvider(
        config=SoundCloudOAuthCaptureConfig(timeout_seconds=0.01)
    )
    with pytest.raises(SoundCloudOAuthCallbackCaptureError):
        timeout_provider._capture_loopback("http://127.0.0.1:8765/callback")


def test_loopback_http_handler_accepts_only_configured_path() -> None:
    for path, expected_status, expected_callback in [
        ("/wrong?code=nope", 404, None),
        ("/callback?code=ok&state=s", 200, "code=ok"),
    ]:
        server = oauth_capture._LoopbackHTTPServer(
            ("127.0.0.1", 0),
            "http://127.0.0.1/callback",
        )
        host, port = server.server_address
        thread = threading.Thread(target=server.handle_request, daemon=True)
        thread.start()
        conn = http.client.HTTPConnection(host, port, timeout=2)
        try:
            conn.request("GET", path)
            response = conn.getresponse()
            response.read()
        finally:
            conn.close()
            thread.join(timeout=2)
            server.server_close()
        assert response.status == expected_status
        if expected_callback is None:
            assert server.callback_url is None
        else:
            assert expected_callback in str(server.callback_url)


def test_token_store_detection_keyring_adapter_and_error_edges(monkeypatch) -> None:
    assert token_store._backend_name(None) == "none"
    assert not token_store.detect_keychain_backend(_MissingMethods()).usable
    assert not token_store.detect_keychain_backend(_Backend(priority=0)).usable
    assert token_store.detect_keychain_backend(_Backend(priority="not-a-number")).usable

    monkeypatch.setattr(
        token_store.importlib,
        "import_module",
        mock.Mock(side_effect=ImportError("missing")),
    )
    assert "not installed" in token_store.detect_keychain_backend(None).reason
    monkeypatch.setattr(
        token_store.importlib,
        "import_module",
        mock.Mock(return_value=SimpleNamespace(get_keyring=mock.Mock(side_effect=RuntimeError))),
    )
    assert "did not provide" in token_store.detect_keychain_backend(None).reason

    backend = _Backend()
    fake_keyring = SimpleNamespace(
        get_keyring=lambda: backend,
        get_password=backend.get_password,
        set_password=backend.set_password,
        delete_password=backend.delete_password,
    )
    monkeypatch.setattr(token_store.importlib, "import_module", lambda _name: fake_keyring)
    adapter = KeyringSoundCloudTokenStorageBackend()
    assert adapter.available
    adapter.set_password("service", "acct", "value")
    assert adapter.get_password("service", "acct") == "value"
    adapter.delete_password("service", "acct")
    assert adapter.get_password("service", "acct") is None

    store = KeychainSoundCloudTokenStore(backend=_Backend(fail_set=True))
    with pytest.raises(SoundCloudTokenStorageError):
        store.save_bundle("acct", SoundCloudOAuthTokenBundle(access_token="a", refresh_token="r"))
    store = KeychainSoundCloudTokenStore(backend=_Backend(fail_get=True))
    with pytest.raises(SoundCloudTokenStorageError):
        store.load_bundle("acct")
    backend = _Backend()
    backend.values[(store.service_name, "acct")] = "{bad json"
    bad_json_store = KeychainSoundCloudTokenStore(backend=backend)
    with pytest.raises(SoundCloudTokenStorageError):
        bad_json_store.load_bundle("acct")
    backend.values[(bad_json_store.service_name, "acct")] = "[]"
    with pytest.raises(SoundCloudTokenStorageError):
        bad_json_store.load_bundle("acct")
    KeychainSoundCloudTokenStore(backend=_Backend(fail_delete=True)).delete_bundle("acct")
    KeychainSoundCloudTokenStore(backend=_Backend(fail_delete=True)).delete_client_secret("client")
    with pytest.raises(SoundCloudTokenStorageError):
        KeychainSoundCloudTokenStore(backend=_Backend()).save_client_secret("", "secret")

    manager = SoundCloudTokenStore(persistent_backend=_Backend(), prefer_persistent=False)
    kind = manager.save_client_secret("client", "session-secret")
    assert kind == SoundCloudTokenKind.SESSION
    assert manager.load_client_secret("client") == "session-secret"
    assert "client_secret=***" in token_store.safe_storage_error_message(
        RuntimeError("failed client_secret=secret")
    )
