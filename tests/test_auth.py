"""Tests for Signal K device authentication flow.

Tests cover:
- AuthToken persistence (load/save to JSON file)
- Token validation via REST API
- Device access request submission
- Polling for approval (approved, denied, timeout)
- Full ensure_auth_token flow
- Config auth fields and env var overrides
- SignalKClient auth token integration
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from config import Config
from signalk_auth import (
    AuthToken,
    _poll_access_request,
    ensure_auth_token,
    load_auth,
    request_device_access,
    save_auth,
    validate_token,
)


# --------------------------------------------------------------------------- #
# Fixtures                                                                     #
# --------------------------------------------------------------------------- #

@pytest.fixture
def tmp_token_file(tmp_path: Path) -> Path:
    """Return a temp path for the token file."""
    return tmp_path / "signalk_token.json"


@pytest.fixture
def config(tmp_token_file: Path) -> Config:
    """Config with a temporary token file path."""
    return Config(auth_token_file=str(tmp_token_file))


def _mock_response(status_code: int = 200, json_data: Any = None, text: str = "") -> MagicMock:
    """Create a mock httpx.Response."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data or {}
    resp.text = text or json.dumps(json_data or {})
    return resp


# --------------------------------------------------------------------------- #
# AuthToken persistence tests                                                  #
# --------------------------------------------------------------------------- #

class TestLoadAuth:
    def test_new_file_generates_uuid(self, config: Config) -> None:
        auth = load_auth(config)
        assert auth.client_id
        assert len(auth.client_id) == 36  # UUID format
        assert auth.token is None
        assert auth.permissions is None

    def test_loads_existing_file(self, config: Config, tmp_token_file: Path) -> None:
        data = {
            "client_id": "test-uuid-1234",
            "token": "eyJhbGciOiJIUzI1NiJ9.test",
            "permissions": "readwrite",
        }
        tmp_token_file.write_text(json.dumps(data))
        auth = load_auth(config)
        assert auth.client_id == "test-uuid-1234"
        assert auth.token == "eyJhbGciOiJIUzI1NiJ9.test"
        assert auth.permissions == "readwrite"

    def test_loads_file_without_token(self, config: Config, tmp_token_file: Path) -> None:
        data = {"client_id": "no-token-uuid"}
        tmp_token_file.write_text(json.dumps(data))
        auth = load_auth(config)
        assert auth.client_id == "no-token-uuid"
        assert auth.token is None

    def test_corrupt_file_generates_new_uuid(self, config: Config, tmp_token_file: Path) -> None:
        tmp_token_file.write_text("not valid json{{{")
        auth = load_auth(config)
        assert auth.client_id  # new UUID generated
        assert auth.token is None

    def test_missing_client_id_generates_new(self, config: Config, tmp_token_file: Path) -> None:
        tmp_token_file.write_text(json.dumps({"token": "abc"}))
        auth = load_auth(config)
        assert auth.client_id  # new UUID
        assert auth.token is None

    def test_consistent_uuid_format(self, config: Config) -> None:
        """Generated client_id should be a valid UUID v4."""
        import uuid
        auth = load_auth(config)
        parsed = uuid.UUID(auth.client_id)
        assert parsed.version == 4


class TestSaveAuth:
    def test_saves_to_file(self, config: Config, tmp_token_file: Path) -> None:
        auth = AuthToken(
            client_id="save-test-uuid",
            token="my-jwt-token",
            permissions="readwrite",
        )
        save_auth(config, auth)
        assert tmp_token_file.exists()
        data = json.loads(tmp_token_file.read_text())
        assert data["client_id"] == "save-test-uuid"
        assert data["token"] == "my-jwt-token"
        assert data["permissions"] == "readwrite"

    def test_creates_parent_dirs(self, tmp_path: Path) -> None:
        nested = tmp_path / "deep" / "nested" / "token.json"
        cfg = Config(auth_token_file=str(nested))
        auth = AuthToken(client_id="nested-test")
        save_auth(cfg, auth)
        assert nested.exists()

    def test_overwrites_existing(self, config: Config, tmp_token_file: Path) -> None:
        auth1 = AuthToken(client_id="first", token="old-token")
        save_auth(config, auth1)
        auth2 = AuthToken(client_id="first", token="new-token")
        save_auth(config, auth2)
        data = json.loads(tmp_token_file.read_text())
        assert data["token"] == "new-token"

    def test_roundtrip(self, config: Config) -> None:
        auth = AuthToken(client_id="rt-uuid", token="rt-token", permissions="readwrite")
        save_auth(config, auth)
        loaded = load_auth(config)
        assert loaded.client_id == auth.client_id
        assert loaded.token == auth.token
        assert loaded.permissions == auth.permissions


# --------------------------------------------------------------------------- #
# Token validation tests                                                       #
# --------------------------------------------------------------------------- #

class TestValidateToken:
    @pytest.mark.asyncio
    async def test_valid_token(self, config: Config) -> None:
        auth = AuthToken(client_id="test", token="valid-jwt")
        mock_resp = _mock_response(200, {"name": "Primrose"})

        with patch("signalk_auth.httpx.AsyncClient") as MockClient:
            mock_ctx = AsyncMock()
            mock_ctx.get = AsyncMock(return_value=mock_resp)
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_ctx)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await validate_token(config, auth)
            assert result is True
            mock_ctx.get.assert_called_once()
            # Verify auth header was sent
            call_kwargs = mock_ctx.get.call_args
            assert "Bearer valid-jwt" in str(call_kwargs)

    @pytest.mark.asyncio
    async def test_expired_token_401(self, config: Config) -> None:
        auth = AuthToken(client_id="test", token="expired-jwt")
        mock_resp = _mock_response(401)

        with patch("signalk_auth.httpx.AsyncClient") as MockClient:
            mock_ctx = AsyncMock()
            mock_ctx.get = AsyncMock(return_value=mock_resp)
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_ctx)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await validate_token(config, auth)
            assert result is False

    @pytest.mark.asyncio
    async def test_forbidden_token_403(self, config: Config) -> None:
        auth = AuthToken(client_id="test", token="readonly-jwt")
        mock_resp = _mock_response(403)

        with patch("signalk_auth.httpx.AsyncClient") as MockClient:
            mock_ctx = AsyncMock()
            mock_ctx.get = AsyncMock(return_value=mock_resp)
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_ctx)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await validate_token(config, auth)
            assert result is False

    @pytest.mark.asyncio
    async def test_no_token_returns_false(self, config: Config) -> None:
        auth = AuthToken(client_id="test", token=None)
        result = await validate_token(config, auth)
        assert result is False

    @pytest.mark.asyncio
    async def test_network_error_returns_false(self, config: Config) -> None:
        auth = AuthToken(client_id="test", token="some-jwt")

        with patch("signalk_auth.httpx.AsyncClient") as MockClient:
            mock_ctx = AsyncMock()
            mock_ctx.get = AsyncMock(side_effect=ConnectionError("unreachable"))
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_ctx)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await validate_token(config, auth)
            assert result is False


# --------------------------------------------------------------------------- #
# Device access request tests                                                  #
# --------------------------------------------------------------------------- #

class TestRequestDeviceAccess:
    @pytest.mark.asyncio
    async def test_successful_request_and_approval(self, config: Config) -> None:
        auth = AuthToken(client_id="test-device-uuid")

        # POST response: request accepted, pending
        post_resp = _mock_response(202, {
            "state": "PENDING",
            "href": "/signalk/v1/access/requests/req-123",
        })

        # Poll response: approved with token
        poll_resp = _mock_response(200, {
            "state": "COMPLETED",
            "statusCode": 200,
            "accessRequest": {
                "permission": "APPROVED",
                "token": "eyJhbGciOiJIUzI1NiJ9.approved",
            },
        })

        with patch("signalk_auth.httpx.AsyncClient") as MockClient:
            mock_ctx = AsyncMock()
            mock_ctx.post = AsyncMock(return_value=post_resp)
            mock_ctx.get = AsyncMock(return_value=poll_resp)
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_ctx)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

            with patch("signalk_auth._poll_access_request",
                       return_value="eyJhbGciOiJIUzI1NiJ9.approved") as mock_poll:
                token = await request_device_access(config, auth)
                assert token == "eyJhbGciOiJIUzI1NiJ9.approved"
                # Verify POST body contained correct fields
                post_call = mock_ctx.post.call_args
                body = post_call.kwargs.get("json") or post_call[1].get("json")
                assert body["clientId"] == "test-device-uuid"
                assert body["permissions"] == "readwrite"
                assert body["description"] == config.auth_device_description

    @pytest.mark.asyncio
    async def test_request_http_error(self, config: Config) -> None:
        auth = AuthToken(client_id="test-uuid")
        post_resp = _mock_response(500, text="Internal Server Error")

        with patch("signalk_auth.httpx.AsyncClient") as MockClient:
            mock_ctx = AsyncMock()
            mock_ctx.post = AsyncMock(return_value=post_resp)
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_ctx)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

            token = await request_device_access(config, auth)
            assert token is None

    @pytest.mark.asyncio
    async def test_request_no_href(self, config: Config) -> None:
        auth = AuthToken(client_id="test-uuid")
        post_resp = _mock_response(200, {"state": "PENDING"})  # no href!

        with patch("signalk_auth.httpx.AsyncClient") as MockClient:
            mock_ctx = AsyncMock()
            mock_ctx.post = AsyncMock(return_value=post_resp)
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_ctx)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

            token = await request_device_access(config, auth)
            assert token is None

    @pytest.mark.asyncio
    async def test_request_network_error(self, config: Config) -> None:
        auth = AuthToken(client_id="test-uuid")

        with patch("signalk_auth.httpx.AsyncClient") as MockClient:
            mock_ctx = AsyncMock()
            mock_ctx.post = AsyncMock(side_effect=ConnectionError("down"))
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_ctx)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

            token = await request_device_access(config, auth)
            assert token is None


# --------------------------------------------------------------------------- #
# Poll access request tests                                                    #
# --------------------------------------------------------------------------- #

class TestPollAccessRequest:
    @pytest.mark.asyncio
    async def test_approved_on_first_poll(self) -> None:
        config = Config(auth_poll_interval_s=0.01, auth_approval_timeout_s=5.0)
        poll_resp = _mock_response(200, {
            "state": "COMPLETED",
            "accessRequest": {"permission": "APPROVED", "token": "jwt-token-123"},
        })

        with patch("signalk_auth.httpx.AsyncClient") as MockClient:
            mock_ctx = AsyncMock()
            mock_ctx.get = AsyncMock(return_value=poll_resp)
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_ctx)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

            token = await _poll_access_request(
                config, "http://localhost:3000/signalk/v1/access/requests/req-1"
            )
            assert token == "jwt-token-123"

    @pytest.mark.asyncio
    async def test_denied(self) -> None:
        config = Config(auth_poll_interval_s=0.01, auth_approval_timeout_s=5.0)
        poll_resp = _mock_response(200, {
            "state": "COMPLETED",
            "accessRequest": {"permission": "DENIED"},
        })

        with patch("signalk_auth.httpx.AsyncClient") as MockClient:
            mock_ctx = AsyncMock()
            mock_ctx.get = AsyncMock(return_value=poll_resp)
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_ctx)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

            token = await _poll_access_request(
                config, "http://localhost:3000/signalk/v1/access/requests/req-2"
            )
            assert token is None

    @pytest.mark.asyncio
    async def test_pending_then_approved(self) -> None:
        config = Config(auth_poll_interval_s=0.01, auth_approval_timeout_s=5.0)
        pending_resp = _mock_response(200, {"state": "PENDING"})
        approved_resp = _mock_response(200, {
            "state": "COMPLETED",
            "accessRequest": {"permission": "APPROVED", "token": "delayed-token"},
        })

        call_count = 0

        async def mock_get(*args: Any, **kwargs: Any) -> MagicMock:
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                return pending_resp
            return approved_resp

        with patch("signalk_auth.httpx.AsyncClient") as MockClient:
            mock_ctx = AsyncMock()
            mock_ctx.get = AsyncMock(side_effect=mock_get)
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_ctx)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

            token = await _poll_access_request(
                config, "http://localhost:3000/signalk/v1/access/requests/req-3"
            )
            assert token == "delayed-token"
            assert call_count == 3

    @pytest.mark.asyncio
    async def test_timeout(self) -> None:
        config = Config(auth_poll_interval_s=0.01, auth_approval_timeout_s=0.05)
        pending_resp = _mock_response(200, {"state": "PENDING"})

        with patch("signalk_auth.httpx.AsyncClient") as MockClient:
            mock_ctx = AsyncMock()
            mock_ctx.get = AsyncMock(return_value=pending_resp)
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_ctx)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

            token = await _poll_access_request(
                config, "http://localhost:3000/signalk/v1/access/requests/req-4"
            )
            assert token is None

    @pytest.mark.asyncio
    async def test_poll_http_error_retries(self) -> None:
        config = Config(auth_poll_interval_s=0.01, auth_approval_timeout_s=5.0)
        error_resp = _mock_response(500)
        approved_resp = _mock_response(200, {
            "state": "COMPLETED",
            "accessRequest": {"permission": "APPROVED", "token": "retry-token"},
        })

        call_count = 0

        async def mock_get(*args: Any, **kwargs: Any) -> MagicMock:
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                return error_resp
            return approved_resp

        with patch("signalk_auth.httpx.AsyncClient") as MockClient:
            mock_ctx = AsyncMock()
            mock_ctx.get = AsyncMock(side_effect=mock_get)
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_ctx)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

            token = await _poll_access_request(
                config, "http://localhost:3000/signalk/v1/access/requests/req-5"
            )
            assert token == "retry-token"

    @pytest.mark.asyncio
    async def test_poll_network_error_retries(self) -> None:
        config = Config(auth_poll_interval_s=0.01, auth_approval_timeout_s=5.0)
        approved_resp = _mock_response(200, {
            "state": "COMPLETED",
            "accessRequest": {"permission": "APPROVED", "token": "net-retry-token"},
        })

        call_count = 0

        async def mock_get(*args: Any, **kwargs: Any) -> MagicMock:
            nonlocal call_count
            call_count += 1
            if call_count <= 1:
                raise ConnectionError("temporary failure")
            return approved_resp

        with patch("signalk_auth.httpx.AsyncClient") as MockClient:
            mock_ctx = AsyncMock()
            mock_ctx.get = AsyncMock(side_effect=mock_get)
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_ctx)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

            token = await _poll_access_request(
                config, "http://localhost:3000/signalk/v1/access/requests/req-6"
            )
            assert token == "net-retry-token"


# --------------------------------------------------------------------------- #
# Full ensure_auth_token flow tests                                            #
# --------------------------------------------------------------------------- #

class TestEnsureAuthToken:
    @pytest.mark.asyncio
    async def test_existing_valid_token(self, config: Config, tmp_token_file: Path) -> None:
        """If a saved token validates, return it without requesting new access."""
        data = {"client_id": "saved-uuid", "token": "valid-jwt", "permissions": "readwrite"}
        tmp_token_file.write_text(json.dumps(data))

        with patch("signalk_auth.validate_token", return_value=True):
            auth = await ensure_auth_token(config)
            assert auth is not None
            assert auth.token == "valid-jwt"
            assert auth.client_id == "saved-uuid"

    @pytest.mark.asyncio
    async def test_invalid_token_requests_new(self, config: Config, tmp_token_file: Path) -> None:
        """If saved token is invalid, request new device access."""
        data = {"client_id": "saved-uuid", "token": "expired-jwt"}
        tmp_token_file.write_text(json.dumps(data))

        with patch("signalk_auth.validate_token", return_value=False), \
             patch("signalk_auth.request_device_access", return_value="new-jwt") as mock_req:
            auth = await ensure_auth_token(config)
            assert auth is not None
            assert auth.token == "new-jwt"
            assert auth.permissions == "readwrite"
            mock_req.assert_called_once()
            # Token should be saved
            saved = json.loads(tmp_token_file.read_text())
            assert saved["token"] == "new-jwt"

    @pytest.mark.asyncio
    async def test_no_saved_token_requests_new(self, config: Config) -> None:
        """If no saved token exists, request device access."""
        with patch("signalk_auth.request_device_access", return_value="fresh-jwt") as mock_req:
            auth = await ensure_auth_token(config)
            assert auth is not None
            assert auth.token == "fresh-jwt"
            mock_req.assert_called_once()

    @pytest.mark.asyncio
    async def test_access_denied_returns_none(self, config: Config) -> None:
        """If device access is denied, return None."""
        with patch("signalk_auth.request_device_access", return_value=None):
            auth = await ensure_auth_token(config)
            assert auth is None

    @pytest.mark.asyncio
    async def test_preserves_client_id_across_retries(
        self, config: Config, tmp_token_file: Path
    ) -> None:
        """The same clientId should be reused across auth attempts."""
        data = {"client_id": "persistent-uuid", "token": "old-jwt"}
        tmp_token_file.write_text(json.dumps(data))

        with patch("signalk_auth.validate_token", return_value=False), \
             patch("signalk_auth.request_device_access", return_value="new-jwt") as mock_req:
            auth = await ensure_auth_token(config)
            # Verify the same clientId was passed to request_device_access
            call_args = mock_req.call_args
            passed_auth = call_args[0][1] if len(call_args[0]) > 1 else call_args[1].get("auth")
            if passed_auth is None:
                passed_auth = call_args[0][1]
            assert passed_auth.client_id == "persistent-uuid"


# --------------------------------------------------------------------------- #
# Config auth fields tests                                                     #
# --------------------------------------------------------------------------- #

class TestConfigAuth:
    def test_default_auth_token_file(self) -> None:
        c = Config()
        assert c.auth_token_file == "/data/signalk_token.json"

    def test_default_auth_device_description(self) -> None:
        c = Config()
        assert c.auth_device_description == "Sea State Analyzer"

    def test_default_auth_approval_timeout(self) -> None:
        c = Config()
        assert c.auth_approval_timeout_s == 300.0

    def test_default_auth_poll_interval(self) -> None:
        c = Config()
        assert c.auth_poll_interval_s == 5.0

    def test_auth_config_overridable(self) -> None:
        c = Config(
            auth_token_file="/tmp/test_token.json",
            auth_device_description="Test Device",
            auth_approval_timeout_s=60.0,
            auth_poll_interval_s=2.0,
        )
        assert c.auth_token_file == "/tmp/test_token.json"
        assert c.auth_device_description == "Test Device"
        assert c.auth_approval_timeout_s == 60.0
        assert c.auth_poll_interval_s == 2.0

    def test_from_env_auth_token_file(self) -> None:
        os.environ["SEA_STATE_AUTH_TOKEN_FILE"] = "/custom/path/token.json"
        try:
            c = Config.from_env()
            assert c.auth_token_file == "/custom/path/token.json"
        finally:
            del os.environ["SEA_STATE_AUTH_TOKEN_FILE"]


# --------------------------------------------------------------------------- #
# SignalKClient auth token integration tests                                   #
# --------------------------------------------------------------------------- #

class TestSignalKClientAuth:
    def test_set_auth_token(self) -> None:
        from signalk_client import SignalKClient
        client = SignalKClient(Config())
        assert client._auth_token is None
        client.set_auth_token("test-jwt-token")
        assert client._auth_token == "test-jwt-token"

    def test_clear_auth_token(self) -> None:
        from signalk_client import SignalKClient
        client = SignalKClient(Config())
        client.set_auth_token("test-jwt")
        client.set_auth_token(None)
        assert client._auth_token is None

    @pytest.mark.asyncio
    async def test_send_works_with_auth_token(self) -> None:
        from signalk_client import SignalKClient
        client = SignalKClient(Config())
        client.set_auth_token("my-jwt")
        client._connected = True
        mock_ws = AsyncMock()
        mock_ws.send = AsyncMock()
        client._ws = mock_ws
        ok = await client.send('{"test": true}')
        assert ok is True
