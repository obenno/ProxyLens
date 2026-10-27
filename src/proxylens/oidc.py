"""Single-process browser code flow. Stores bearer tokens, never local memberships."""

import base64
import hashlib
import re
import secrets
import time
from dataclasses import dataclass
from urllib.parse import urlencode, urlsplit

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response

from proxylens.identity import AuthorityUnavailable, GroupState, IdentityError, Principal
from proxylens.keycloak import IdentitySettings, KeycloakAuthority, TokenVerifier


@dataclass(frozen=True)
class Login:
    nonce: str
    verifier: str
    expires_at: float


@dataclass(frozen=True)
class Session:
    token: str
    csrf: str
    expires_at: float


_CALLBACK_STATE_RE = re.compile(r"[A-Za-z0-9_-]{1,256}\Z")


def _valid_callback_state(value: object) -> bool:
    """Validate bounded URL-safe ASCII before constant-time comparison."""
    return isinstance(value, str) and _CALLBACK_STATE_RE.fullmatch(value) is not None


def principal_json(principal: Principal) -> dict:
    return {
        "issuer": principal.issuer,
        "subject": principal.subject,
        "roles": sorted(principal.roles),
        "group_ids": sorted(principal.group_ids),
        "expires_at": principal.expires_at,
        "verification": principal.verification,
    }


class IdentityService:
    def __init__(self, settings: IdentitySettings, client: httpx.AsyncClient):
        self.settings = settings
        self.client = client
        self.verifier = TokenVerifier(settings, client)
        self.authority = KeycloakAuthority(settings, client)
        self.logins: dict[str, Login] = {}
        self.sessions: dict[str, Session] = {}
        url = urlsplit(settings.redirect_uri)
        self.origin = f"{url.scheme}://{url.netloc}"
        self.secure = url.scheme == "https"
        self.cookie = "__Host-proxylens" if self.secure else "proxylens-local"
        self.login_cookie = "__Host-proxylens-login" if self.secure else "proxylens-login-local"

    def prune(self) -> None:
        now = time.time()
        self.logins = {key: value for key, value in self.logins.items() if value.expires_at > now}
        self.sessions = {
            key: value for key, value in self.sessions.items() if value.expires_at > now
        }

    def cookie_on(self, response: Response, name: str, value: str, max_age: int) -> None:
        response.set_cookie(
            name,
            value,
            max_age=max_age,
            httponly=True,
            secure=self.secure,
            samesite="lax",
            path="/",
        )

    async def authenticate(self, request: Request) -> Principal:
        authorization = request.headers.get("authorization")
        if authorization is not None:
            parts = authorization.split()
            if len(parts) != 2 or parts[0].lower() != "bearer":
                raise IdentityError("invalid_token")
            token = parts[1]
        else:
            self.prune()
            session = self.sessions.get(request.cookies.get(self.cookie, ""))
            if session is None:
                raise IdentityError("authentication_required")
            token = session.token
            if request.method not in {"GET", "HEAD", "OPTIONS"} and (
                request.headers.get("origin") != self.origin
                or not secrets.compare_digest(
                    request.headers.get("x-proxylens-csrf", ""), session.csrf
                )
            ):
                raise HTTPException(403, "csrf_rejected")
        principal = await self.verifier.validate(token)
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            # Scope-specific writes must also call require_group in identity.py.
            await self.authority.require_available()
        return principal

    async def login(self) -> Response:
        self.prune()
        if len(self.logins) >= 1024:
            raise HTTPException(503, "login_capacity")
        state, nonce, verifier = (secrets.token_urlsafe(32) for _ in range(3))
        self.logins[state] = Login(nonce, verifier, time.time() + 300)
        try:
            await self.authority.require_available()
        except BaseException:
            self.logins.pop(state, None)
            raise
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
        query = urlencode(
            {
                "client_id": self.settings.browser_client,
                "response_type": "code",
                "scope": "openid",
                "redirect_uri": self.settings.redirect_uri,
                "state": state,
                "nonce": nonce,
                "code_challenge_method": "S256",
                "code_challenge": challenge.rstrip(b"=").decode(),
            }
        )
        response = RedirectResponse(
            f"{self.settings.issuer}/protocol/openid-connect/auth?{query}", status_code=302
        )
        self.cookie_on(response, self.login_cookie, state, 300)
        return response

    async def callback(self, request: Request) -> Response:
        self.prune()
        state = request.query_params.get("state", "")
        cookie = request.cookies.get(self.login_cookie, "")
        if (
            not _valid_callback_state(state)
            or not _valid_callback_state(cookie)
            or not secrets.compare_digest(state, cookie)
        ):
            raise IdentityError("invalid_callback")
        login = self.logins.pop(state, None)  # single-use, including rejected callbacks
        code = request.query_params.get("code", "")
        if (
            login is None
            or not code
            or len(code) > 4096
            or request.query_params.get("error")
            or request.query_params.get("iss") != self.settings.issuer
        ):
            raise IdentityError("invalid_callback")
        if len(self.sessions) >= 4096:
            raise HTTPException(503, "session_capacity")
        await self.authority.require_available()
        try:
            response = await self.client.post(
                f"{self.settings.protocol_url}/token",
                data={
                    "grant_type": "authorization_code",
                    "client_id": self.settings.browser_client,
                    "code": code,
                    "redirect_uri": self.settings.redirect_uri,
                    "code_verifier": login.verifier,
                },
                timeout=3,
            )
            response.raise_for_status()
            tokens = response.json()
            principal = await self.verifier.validate(tokens["access_token"])
            identity = await self.verifier.decode(tokens["id_token"], self.settings.browser_client)
            if (
                identity.get("nonce") != login.nonce
                or identity.get("typ") != "ID"
                or identity["sub"] != principal.subject
                or identity.get("azp") != self.settings.browser_client
            ):
                raise IdentityError("invalid_callback")
            if "at_hash" in identity:
                digest = hashlib.sha256(tokens["access_token"].encode()).digest()[:16]
                expected = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
                if identity["at_hash"] != expected:
                    raise IdentityError("invalid_callback")
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            raise IdentityError("invalid_callback") from None
        # New authentication requires current authority, even with warmed signing keys.
        for group_id in principal.group_ids:
            if (await self.authority.lookup_group(group_id)).state != GroupState.ACTIVE:
                raise IdentityError("group_unusable")
        session_id, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        if len(self.sessions) >= 4096:
            raise HTTPException(503, "session_capacity")
        self.sessions.pop(request.cookies.get(self.cookie, ""), None)
        self.sessions[session_id] = Session(tokens["access_token"], csrf, principal.expires_at)
        result = JSONResponse({**principal_json(principal), "csrf_token": csrf})
        self.cookie_on(
            result, self.cookie, session_id, max(0, int(principal.expires_at - time.time()))
        )
        result.delete_cookie(self.login_cookie, path="/", secure=self.secure, httponly=True)
        return result


def install_identity_routes(app: FastAPI) -> None:
    @app.exception_handler(IdentityError)
    async def invalid_identity(request: Request, exc: IdentityError):
        return JSONResponse(
            {"detail": "invalid_identity"},
            status_code=401,
            headers={"WWW-Authenticate": "Bearer", "Cache-Control": "no-store"},
        )

    @app.exception_handler(AuthorityUnavailable)
    async def unavailable(request: Request, exc: AuthorityUnavailable):
        return JSONResponse(
            {"detail": "identity_authority_unavailable"},
            status_code=503,
            headers={"Cache-Control": "no-store"},
        )

    @app.middleware("http")
    async def private_responses(request: Request, call_next):
        response = await call_next(request)
        if request.url.path.startswith(("/oidc/", "/api/")):
            response.headers["Cache-Control"] = "no-store"
            response.headers["Referrer-Policy"] = "no-referrer"
        return response

    @app.get("/oidc/login")
    async def login(request: Request):
        return await request.app.state.identity.login()

    @app.get("/oidc/callback")
    async def callback(request: Request):
        return await request.app.state.identity.callback(request)

    @app.get("/api/me")
    async def me(request: Request):
        principal = await request.app.state.identity.authenticate(request)
        return principal_json(principal)

    @app.post("/oidc/logout")
    async def logout(request: Request):
        identity = request.app.state.identity
        await identity.authenticate(request)
        identity.sessions.pop(request.cookies.get(identity.cookie, ""), None)
        response = Response(status_code=204)
        response.delete_cookie(identity.cookie, path="/", secure=identity.secure, httponly=True)
        return response
