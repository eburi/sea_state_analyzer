"""Signal K device authentication via the access request flow.

Implements the Signal K device access request protocol to obtain a JWT
token with ``readwrite`` permissions.  The token is persisted to a JSON
file so it survives container restarts.

Flow:
    1. Load saved ``clientId`` + ``token`` from ``auth_token_file``.
    2. If a token exists, validate it with a test REST call.
    3. If no valid token, POST a device access request to the server.
    4. Poll the request status until the user approves (or denies/timeout).
    5. On approval, save the token and return it.

The token is used as an ``Authorization: Bearer`` header on the WebSocket
connection to enable delta writes.

See also:
    https://signalk.org/specification/1.7.0/doc/access_requests.html
"""
from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import httpx

from config import Config

logger = logging.getLogger(__name__)


@dataclass
class AuthToken:
    """Persisted authentication state."""
    client_id: str
    token: Optional[str] = None
    permissions: Optional[str] = None


def _token_file_path(config: Config) -> Path:
    """Resolve the token file path from config."""
    return Path(config.auth_token_file)


def load_auth(config: Config) -> AuthToken:
    """Load saved auth state from disk, or create a new clientId.

    If the file doesn't exist or is corrupt, a fresh clientId is
    generated and an AuthToken with no token is returned.
    """
    path = _token_file_path(config)
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            auth = AuthToken(
                client_id=data["client_id"],
                token=data.get("token"),
                permissions=data.get("permissions"),
            )
            logger.info("Loaded auth state: clientId=%s, has_token=%s",
                        auth.client_id, auth.token is not None)
            return auth
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            logger.warning("Corrupt auth file %s: %s — generating new clientId", path, exc)

    # Generate a new clientId
    auth = AuthToken(client_id=str(uuid.uuid4()))
    logger.info("Generated new clientId: %s", auth.client_id)
    return auth


def save_auth(config: Config, auth: AuthToken) -> None:
    """Persist auth state to disk."""
    path = _token_file_path(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "client_id": auth.client_id,
        "token": auth.token,
        "permissions": auth.permissions,
    }
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    logger.info("Saved auth state to %s", path)


async def validate_token(config: Config, auth: AuthToken) -> bool:
    """Check whether the saved token is still valid.

    Makes a lightweight authenticated GET to the Signal K REST API.
    Returns True if the server accepts the token.
    """
    if not auth.token:
        return False

    url = f"{config.base_url}/signalk/v1/api/vessels/self"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                url,
                headers={"Authorization": f"Bearer {auth.token}"},
            )
            if resp.status_code == 200:
                logger.info("Existing token is valid")
                return True
            elif resp.status_code in (401, 403):
                logger.warning("Existing token rejected (HTTP %d) — will re-request",
                               resp.status_code)
                return False
            else:
                logger.warning("Token validation got HTTP %d — treating as invalid",
                               resp.status_code)
                return False
    except Exception as exc:
        logger.warning("Token validation failed: %s — treating as invalid", exc)
        return False


async def request_device_access(
    config: Config,
    auth: AuthToken,
) -> Optional[str]:
    """Request device access and poll until approved, denied, or timeout.

    Posts an access request to the Signal K server, then polls the
    returned href until the state changes from PENDING to COMPLETED.

    Logs clear messages telling the user to approve the request in the
    Signal K admin UI.

    Args:
        config: App configuration.
        auth: Auth state (must have a valid client_id).

    Returns:
        The JWT token string on approval, or None on denial/timeout/error.
    """
    url = f"{config.base_url}/signalk/v1/access/requests"
    body = {
        "clientId": auth.client_id,
        "description": config.auth_device_description,
        "permissions": "readwrite",
    }

    logger.info("Requesting device access: %s", url)
    logger.info("  clientId: %s", auth.client_id)
    logger.info("  description: %s", config.auth_device_description)
    logger.info("  permissions: readwrite")

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(url, json=body)
            if resp.status_code not in (200, 202):
                logger.error(
                    "Device access request failed: HTTP %d — %s",
                    resp.status_code, resp.text[:200],
                )
                return None

            data = resp.json()
            state = data.get("state", "")
            href = data.get("href", "")

            if not href:
                logger.error("No href in access request response: %s", data)
                return None

            logger.info("Access request submitted — state=%s, href=%s", state, href)
            logger.info("=" * 60)
            logger.info("ACTION REQUIRED: Approve this device in Signal K admin UI")
            logger.info("  Go to: %s → Security → Access Requests", config.base_url)
            logger.info("  Look for: '%s'", config.auth_device_description)
            logger.info("  Grant: Read/Write access")
            logger.info("=" * 60)

    except Exception as exc:
        logger.error("Failed to submit device access request: %s", exc)
        return None

    # Poll for approval
    poll_url = f"{config.base_url}{href}"
    return await _poll_access_request(config, poll_url)


async def _poll_access_request(
    config: Config,
    poll_url: str,
) -> Optional[str]:
    """Poll an access request URL until COMPLETED or timeout.

    Args:
        config: App configuration (for timeout and interval settings).
        poll_url: Full URL to poll (base_url + href from initial response).

    Returns:
        JWT token on approval, None on denial/timeout/error.
    """
    import asyncio

    elapsed = 0.0
    timeout = config.auth_approval_timeout_s
    interval = config.auth_poll_interval_s

    logger.info("Polling for approval (timeout=%.0fs, interval=%.0fs)…",
                timeout, interval)

    while elapsed < timeout:
        await asyncio.sleep(interval)
        elapsed += interval

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(poll_url)
                if resp.status_code != 200:
                    logger.debug("Poll returned HTTP %d, retrying…", resp.status_code)
                    continue

                data = resp.json()
                state = data.get("state", "")

                if state == "PENDING":
                    if int(elapsed) % 30 == 0:  # Log every 30s
                        logger.info(
                            "Still waiting for approval (%.0f/%.0fs)…",
                            elapsed, timeout,
                        )
                    continue

                if state == "COMPLETED":
                    access_req = data.get("accessRequest", {})
                    permission = access_req.get("permission", "")
                    token = access_req.get("token")

                    if permission == "APPROVED" and token:
                        logger.info("Device access APPROVED — received JWT token")
                        return token
                    elif permission == "DENIED":
                        logger.error("Device access DENIED by administrator")
                        return None
                    else:
                        logger.error(
                            "Unexpected access request result: permission=%s, has_token=%s",
                            permission, token is not None,
                        )
                        return None

                # Unknown state
                logger.warning("Unexpected access request state: %s", state)

        except Exception as exc:
            logger.warning("Poll error: %s — will retry", exc)

    logger.error(
        "Timed out waiting for device access approval (%.0fs). "
        "Please approve the request in Signal K admin UI and restart.",
        timeout,
    )
    return None


async def ensure_auth_token(config: Config) -> Optional[AuthToken]:
    """High-level auth flow: load, validate, or request a new token.

    This is the main entry point for the auth module.  Call this on
    startup before connecting the WebSocket.

    Returns:
        AuthToken with a valid token, or None if auth could not be obtained.
    """
    auth = load_auth(config)

    # Try existing token first
    if auth.token:
        if await validate_token(config, auth):
            return auth
        else:
            logger.info("Saved token is invalid — requesting new device access")
            auth.token = None
            auth.permissions = None

    # Request new device access
    token = await request_device_access(config, auth)
    if token:
        auth.token = token
        auth.permissions = "readwrite"
        save_auth(config, auth)
        return auth

    return None
