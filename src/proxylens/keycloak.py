"""Keycloak-only token validation and bounded public signing-key cache."""

import asyncio
import json
import math
import time
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit
from uuid import UUID

import httpx
import jwt

from proxylens.identity import (
    AuthorityUnavailable,
    GroupEvidence,
    GroupState,
    IdentityError,
    Principal,
)

JWKS_MAX_BYTES = 65_536
JWKS_REFRESH_TIMEOUT_SECONDS = 2.0


@dataclass(frozen=True)
class IdentitySettings:
    issuer: str
    internal_url: str
    audience: str = "proxylens-api"
    browser_client: str = "proxylens-browser"
    admin_client: str = "proxylens-admin"
    admin_secret_file: str = "/run/secrets/keycloak_client_secret"
    redirect_uri: str = "http://localhost:8001/oidc/callback"
    jwks_ttl: int = 300
    refresh_interval: int = 15
    clock_skew: int = 5
    jwks_timeout_seconds: float = JWKS_REFRESH_TIMEOUT_SECONDS

    def __post_init__(self):
        if not (
            15 <= self.jwks_ttl <= 300
            and 1 <= self.refresh_interval <= self.jwks_ttl
            and 0 <= self.clock_skew <= 30
            and isinstance(self.jwks_timeout_seconds, (int, float))
            and not isinstance(self.jwks_timeout_seconds, bool)
            and math.isfinite(self.jwks_timeout_seconds)
            and 0 < self.jwks_timeout_seconds <= 10
        ):
            raise ValueError("invalid identity cache or skew limits")
        for value, path, public in (
            (self.issuer, "/realms/proxylens", True),
            (self.redirect_uri, "/oidc/callback", True),
            (self.internal_url, "", False),
        ):
            url = urlsplit(value)
            if (
                url.scheme not in {"http", "https"}
                or not url.hostname
                or url.username
                or url.password
                or url.query
                or url.fragment
                or url.path != path
                or (
                    public
                    and url.scheme == "http"
                    and url.hostname not in {"localhost", "127.0.0.1", "::1"}
                )
            ):
                raise ValueError("invalid identity endpoint")

    @property
    def protocol_url(self) -> str:
        return f"{self.internal_url}/realms/proxylens/protocol/openid-connect"


class TokenVerifier:
    def __init__(
        self, settings: IdentitySettings, client: httpx.AsyncClient, *, clock=time.monotonic
    ):
        self.settings = settings
        self.client = client
        self.clock = clock
        self.keys: dict[str, jwt.PyJWK] = {}
        self.fetched_at = float("-inf")
        self.attempted_at = float("-inf")
        self.lock = asyncio.Lock()

    async def _key(self, kid: str) -> jwt.PyJWK:
        async with self.lock:
            now = self.clock()
            if kid in self.keys and now < self.fetched_at + self.settings.jwks_ttl:
                return self.keys[kid]
            if now < self.attempted_at + self.settings.refresh_interval:
                raise IdentityError("signing_key_unavailable")
            self.attempted_at = now
            try:
                async with asyncio.timeout(self.settings.jwks_timeout_seconds):
                    async with self.client.stream(
                        "GET",
                        f"{self.settings.protocol_url}/certs",
                        timeout=self.settings.jwks_timeout_seconds,
                        follow_redirects=False,
                    ) as response:
                        if response.status_code != 200:
                            raise httpx.HTTPStatusError(
                                "unexpected JWKS response",
                                request=response.request,
                                response=response,
                            )
                        if (
                            response.headers.get("content-encoding", "identity").lower()
                            != "identity"
                        ):
                            raise ValueError("unsupported keyset encoding")
                        length = response.headers.get("content-length")
                        if length is not None and (
                            not length.isdecimal()
                            or len(length) > 20
                            or int(length) > JWKS_MAX_BYTES
                        ):
                            raise ValueError("oversized keyset")
                        body = bytearray()
                        async for chunk in response.aiter_bytes():
                            if len(body) + len(chunk) > JWKS_MAX_BYTES:
                                raise ValueError("oversized keyset")
                            body.extend(chunk)
                    keys = json.loads(bytes(body))["keys"]
                    if not isinstance(keys, list) or len(keys) > 32:
                        raise ValueError("invalid keyset")
                    parsed = {
                        item["kid"]: jwt.PyJWK(item, algorithm="RS256")
                        for item in keys
                        if item.get("kty") == "RSA"
                        and item.get("alg") == "RS256"
                        and item.get("use") == "sig"
                    }
                    if not parsed:
                        raise ValueError("empty keyset")
            except (
                httpx.HTTPError,
                TimeoutError,
                ValueError,
                KeyError,
                TypeError,
                AttributeError,
                jwt.PyJWTError,
            ):
                raise AuthorityUnavailable("signing_keys_unavailable") from None
            self.keys = parsed
            self.fetched_at = self.clock()
            if kid not in self.keys:
                raise IdentityError("unknown_signing_key")
            return self.keys[kid]

    async def decode(self, token: str, audience: str) -> dict:
        try:
            if not isinstance(token, str) or len(token) > 16384:
                raise IdentityError("invalid_token")
            header = jwt.get_unverified_header(token)
            if (
                header.get("alg") != "RS256"
                or not isinstance(header.get("kid"), str)
                or not 1 <= len(header["kid"]) <= 256
                or header.get("crit")
            ):
                raise IdentityError("invalid_token")
            key = await self._key(header["kid"])
            claims = jwt.decode(
                token,
                key,
                algorithms=["RS256"],
                audience=audience,
                issuer=self.settings.issuer,
                leeway=self.settings.clock_skew,
                options={"require": ["iss", "aud", "sub", "exp", "iat"]},
            )
            stable_id(claims["sub"])
            for name in ("exp", "iat", "nbf"):
                if name in claims and type(claims[name]) is not int:
                    raise ValueError("invalid time")
            if not 0 < claims["exp"] - claims["iat"] <= 300 or claims["exp"] <= time.time():
                raise ValueError("expired or excessive lifetime")
            return claims
        except (jwt.PyJWTError, ValueError, TypeError):
            raise IdentityError("invalid_token") from None

    async def validate(self, token: str) -> Principal:
        claims = await self.decode(token, self.settings.audience)
        try:
            roles = claims["resource_access"][self.settings.audience]["roles"]
            groups = claims["proxylens_group_ids"]
            if (
                claims.get("typ") != "Bearer"
                or claims["azp"] != self.settings.browser_client
                or claims["proxylens_groups_flat"] is not True
                or not isinstance(roles, list)
                or len(roles) > 64
                or any(not isinstance(role, str) or not 1 <= len(role) <= 128 for role in roles)
                or not isinstance(groups, list)
                or len(groups) > 256
            ):
                raise ValueError("invalid claims")
            for group in groups:
                stable_id(group)
            return Principal(
                issuer=claims["iss"],
                subject=claims["sub"],
                roles=frozenset(roles),
                group_ids=frozenset(groups),
                expires_at=claims["exp"],
                verified_at=time.time(),
                signing_key_valid_until=time.time()
                + max(0, self.fetched_at + self.settings.jwks_ttl - self.clock()),
            )
        except (KeyError, TypeError, ValueError):
            raise IdentityError("invalid_claims") from None


def stable_id(value: str) -> str:
    """This realm uses native Keycloak UUID identities, never names/federated IDs."""
    if not isinstance(value, str) or str(UUID(value)) != value:
        raise ValueError("invalid stable identity")
    return value


class KeycloakAuthority:
    """Read-only Admin adapter. No membership mirror or existence cache."""

    def __init__(self, settings: IdentitySettings, client: httpx.AsyncClient):
        self.settings = settings
        self.client = client

    async def _admin_token(self) -> str:
        try:
            secret = Path(self.settings.admin_secret_file).read_text().strip()
            if not secret:
                raise ValueError("missing credential")
            response = await self.client.post(
                f"{self.settings.protocol_url}/token",
                data={
                    "grant_type": "client_credentials",
                    "client_id": self.settings.admin_client,
                    "client_secret": secret,
                },
                timeout=2,
            )
            response.raise_for_status()
            token = response.json()["access_token"]
            if not isinstance(token, str) or not token:
                raise ValueError("invalid token")
            return token
        except (OSError, ValueError, KeyError, TypeError, httpx.HTTPError):
            raise AuthorityUnavailable("group_authority_unavailable") from None

    async def _get(self, path: str) -> httpx.Response:
        token = await self._admin_token()
        try:
            response = await self.client.get(
                f"{self.settings.internal_url}/admin/realms/proxylens/{path}",
                headers={"Authorization": f"Bearer {token}"},
                timeout=2,
            )
            if response.status_code != 404:
                response.raise_for_status()
            return response
        except httpx.HTTPError:
            raise AuthorityUnavailable("group_authority_unavailable") from None

    async def require_available(self) -> None:
        response = await self._get("groups?first=0&max=1&briefRepresentation=true")
        try:
            if response.status_code != 200 or not isinstance(response.json(), list):
                raise ValueError("invalid group authority")
        except ValueError:
            raise AuthorityUnavailable("group_authority_unavailable") from None

    async def lookup_group(self, group_id: str) -> GroupEvidence:
        stable_id(group_id)
        response = await self._get(f"groups/{group_id}")
        if response.status_code == 404:
            state = GroupState.MISSING
        else:
            try:
                group = response.json()
                if group["id"] != group_id:
                    raise ValueError("identity mismatch")
                # Both descendants and containers with children are unsupported.
                count = group.get("subGroupCount")
                if type(count) is not int or count < 0:
                    raise ValueError("missing hierarchy evidence")
                state = GroupState.NESTED if group.get("parentId") or count else GroupState.ACTIVE
            except (ValueError, KeyError, TypeError, AttributeError):
                raise AuthorityUnavailable("group_authority_unavailable") from None
        return GroupEvidence(self.settings.issuer, group_id, state, time.time())

    async def reconcile(
        self, group_ids: Iterable[str], mark_unusable: Callable[[GroupEvidence], Awaitable[None]]
    ) -> None:
        """Resource worker supplies a transactional orphan/audit hook. Never auto-repair."""
        for group_id in dict.fromkeys(group_ids):
            evidence = await self.lookup_group(group_id)
            if evidence.state != GroupState.ACTIVE:
                await mark_unusable(evidence)
