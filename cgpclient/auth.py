from __future__ import annotations

import logging
import uuid
from pathlib import Path
from time import time
from typing import Protocol

import jwt
import requests  # type: ignore
from pydantic import BaseModel

from cgpclient.utils import APIM_BASE_URL, REQUEST_TIMEOUT_SECS, CGPClientException

log = logging.getLogger(__name__)


class NHSOAuthToken(BaseModel):
    access_token: str
    expires_in: str
    token_type: str
    issued_at: str


class AuthProvider(Protocol):
    """Protocol for authentication providers"""

    def get_headers(self) -> dict[str, str]:
        """Return HTTP headers for authentication"""
        ...


class NoAuthProvider:
    """No authentication provider for sandbox environments"""

    def get_headers(self) -> dict[str, str]:
        log.debug("No API authentication")
        return {}


class APIKeyAuthProvider:
    """API key authentication provider"""

    def __init__(self, api_key: str, api_host: str):
        self.api_key = api_key
        self.api_host = api_host

    def get_headers(self) -> dict[str, str]:
        log.debug("Using API key authentication")
        if APIM_BASE_URL in self.api_host:
            logging.debug("Using APIM API key header")
            return {"apikey": self.api_key}

        log.debug("Using standard API key header")
        return {"X-API-Key": self.api_key}


class OAuthProvider:
    """OAuth JWT authentication provider for NHS APIM"""

    def __init__(
        self, api_key: str, private_key_pem: Path, apim_kid: str, api_host: str
    ):
        self.api_key = api_key
        self.private_key_pem = private_key_pem
        self.apim_kid = apim_kid
        self.api_host = api_host
        self._oauth_token: NHSOAuthToken | None = None

    def get_headers(self) -> dict[str, str]:
        log.debug("Using signed JWT authentication")
        return {"Authorization": f"Bearer {self.get_access_token()}"}

    def get_access_token(self) -> str:
        return self._get_oauth_token().access_token

    def _get_oauth_token(self) -> NHSOAuthToken:
        if self._oauth_token is None or self._is_token_expired():
            log.info("Requesting new OAuth token")
            self._oauth_token = self._request_access_token()
        return self._oauth_token

    def _is_token_expired(self) -> bool:
        if self._oauth_token is None:
            return True
        return int(time()) > int(self._oauth_token.issued_at) + int(
            self._oauth_token.expires_in
        )

    def _request_access_token(self, api_host: str | None = None) -> NHSOAuthToken:
        if api_host is None:
            api_host = self.api_host
        oauth_endpoint = f"https://{api_host}/oauth2/token"
        log.info("Requesting OAuth token from: %s", oauth_endpoint)

        response = requests.post(
            url=oauth_endpoint,
            headers={"content-type": "application/x-www-form-urlencoded"},
            data={
                "grant_type": "client_credentials",
                "client_assertion_type": (
                    "urn:ietf:params:oauth:client-assertion-type:jwt-bearer"
                ),
                "client_assertion": self._get_jwt(oauth_endpoint),
            },
            timeout=REQUEST_TIMEOUT_SECS,
        )

        if response.ok:
            log.info("Got successful response from OAuth server")
            return NHSOAuthToken.model_validate(response.json())

        raise CGPClientException(
            f"Failed to get OAuth token, status code: {response.status_code}"
        )

    def _get_jwt(self, oauth_endpoint: str) -> str:
        with open(self.private_key_pem, "r", encoding="utf-8") as pem:
            private_key = pem.read()

        expiry_time = int(time()) + (5 * 60)  # 5 mins in the future

        log.debug(
            "Creating JWT for KID: %s and signing with private key: %s",
            self.apim_kid,
            self.private_key_pem,
        )

        return jwt.encode(
            payload={
                "sub": self.api_key,
                "iss": self.api_key,
                "jti": str(uuid.uuid4()),
                "aud": oauth_endpoint,
                "exp": expiry_time,
            },
            key=private_key,
            algorithm="RS512",
            headers={"kid": self.apim_kid},
        )


class SandboxAuthProvider:
    """Authentication provider for sandbox environments"""

    def get_headers(self) -> dict[str, str]:
        log.debug("Skipping authentication for sandbox environment")
        return {}


def create_auth_provider(
    api_host: str,
    api_key: str | None = None,
    private_key_pem: Path | None = None,
    apim_kid: str | None = None,
) -> AuthProvider:
    """Factory function to create appropriate auth provider"""

    if api_host.startswith("sandbox."):
        return SandboxAuthProvider()

    if private_key_pem is not None and apim_kid is not None and api_key is not None:
        return OAuthProvider(api_key, private_key_pem, apim_kid, api_host)

    if api_key is not None:
        return APIKeyAuthProvider(api_key, api_host)

    return NoAuthProvider()
