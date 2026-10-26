import asyncio
import time

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from proxylens.identity import AuthorityUnavailable, Capability, IdentityError
from proxylens.keycloak import IdentitySettings, TokenVerifier

ISSUER = "https://identity.example/realms/proxylens"
SUBJECT = "11111111-1111-4111-8111-111111111111"
G1 = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
G2 = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
PRIVATE = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def claims(**overrides):
    now = int(time.time())
    return {
        "iss": ISSUER,
        "aud": "proxylens-api",
        "sub": SUBJECT,
        "iat": now,
        "exp": now + 300,
        "typ": "Bearer",
        "azp": "proxylens-browser",
        "resource_access": {"proxylens-api": {"roles": ["group-member"]}},
        "proxylens_group_ids": [G1, G2],
        "proxylens_groups_flat": True,
        **overrides,
    }


def signed(payload=None, key=PRIVATE, kid="signing-key", algorithm="RS256"):
    return jwt.encode(payload or claims(), key, algorithm=algorithm, headers={"kid": kid})


def jwks(key=PRIVATE, kid="signing-key"):
    return {
        "keys": [
            {
                **jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key(), as_dict=True),
                "kid": kid,
                "alg": "RS256",
                "use": "sig",
            }
        ]
    }


def settings(**kwargs):
    return IdentitySettings(issuer=ISSUER, internal_url="https://identity.example", **kwargs)


def test_signed_principal_uses_stable_subject_and_union_of_group_scope():
    async def check():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda request: httpx.Response(200, json=jwks()))
        ) as client:
            principal = await TokenVerifier(settings(), client).validate(signed())
            assert principal.subject == SUBJECT
            assert principal.issuer == ISSUER
            assert principal.group_ids == frozenset({G1, G2})
            assert principal.can(Capability.READ, G1)
            assert principal.can(Capability.READ, G2)
            assert principal.can(Capability.USE, G1)
            assert not principal.can(Capability.MANAGE, G1)
            assert not principal.can(Capability.READ, "cccccccc-cccc-4ccc-8ccc-cccccccccccc")

    asyncio.run(check())


@pytest.mark.parametrize(
    "change",
    [
        {"iss": "https://other.example/realms/proxylens"},
        {"aud": "other-api"},
        {"exp": 1},
        {"nbf": int(time.time()) + 600},
        {"sub": ""},
        {"sub": "user-name"},
        {"iat": "1"},
        {"exp": True},
        {"resource_access": []},
        {"resource_access": {"other-api": {"roles": ["platform-admin"]}}},
        {"resource_access": {"proxylens-api": {"roles": "platform-admin"}}},
        {"resource_access": {"proxylens-api": {"roles": [7]}}},
        {"proxylens_group_ids": "engineering"},
        {"proxylens_group_ids": ["/engineering/sub"]},
        {"proxylens_group_ids": [5]},
        {"proxylens_groups_flat": False},
        {"proxylens_groups_flat": "true"},
        {"azp": "proxylens-admin"},
        {"typ": "ID"},
        {"exp": int(time.time()) + 36000},
    ],
)
def test_invalid_signed_claims_are_rejected(change):
    async def check():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda request: httpx.Response(200, json=jwks()))
        ) as client:
            with pytest.raises(IdentityError):
                await TokenVerifier(settings(), client).validate(signed(claims(**change)))

    asyncio.run(check())


@pytest.mark.parametrize(
    "missing",
    [
        "iss",
        "aud",
        "sub",
        "exp",
        "iat",
        "resource_access",
        "proxylens_group_ids",
        "proxylens_groups_flat",
        "azp",
    ],
)
def test_required_claim_cannot_be_omitted(missing):
    payload = claims()
    del payload[missing]

    async def check():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda request: httpx.Response(200, json=jwks()))
        ) as client:
            with pytest.raises(IdentityError):
                await TokenVerifier(settings(), client).validate(signed(payload))

    asyncio.run(check())


def test_wrong_signature_unsigned_and_symmetric_tokens_fail_closed():
    wrong_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    tokens = [
        "malformed",
        signed(key=wrong_key),
        signed(key=None, algorithm="none"),
        signed(key=b"s" * 32, algorithm="HS256"),
    ]

    async def check():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda request: httpx.Response(200, json=jwks()))
        ) as client:
            verifier = TokenVerifier(settings(), client)
            for token in tokens:
                with pytest.raises(IdentityError):
                    await verifier.validate(token)

    asyncio.run(check())


def test_key_rotation_cache_deadline_and_unknown_kid_refresh_are_bounded():
    now = [0.0]
    calls = []
    response = [jwks()]

    def handle(request):
        calls.append(request)
        if response[0] is None:
            raise httpx.ConnectError("offline")
        return httpx.Response(200, json=response[0])

    async def check():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            verifier = TokenVerifier(settings(jwks_ttl=60), client, clock=lambda: now[0])
            await verifier.validate(signed())
            await verifier.validate(signed())
            for index in range(30):
                with pytest.raises(IdentityError):
                    await verifier.validate(signed(kid=f"attacker-{index}"))
            assert len(calls) == 1
            now[0] = 16
            response[0] = jwks(kid="rotated")
            await verifier.validate(signed(kid="rotated"))
            assert len(calls) == 2
            response[0] = None
            now[0] = 70
            await verifier.validate(signed(kid="rotated"))
            now[0] = 76
            with pytest.raises(AuthorityUnavailable):
                await verifier.validate(signed(kid="rotated"))
            with pytest.raises(IdentityError):
                await verifier.validate(signed(kid="rotated"))
            assert len(calls) == 3

    asyncio.run(check())


@pytest.mark.parametrize(
    "roles,groups,read,use,manage",
    [
        (["group-member"], [G1, G2], True, True, False),
        (["group-admin"], [G1], True, True, True),
        (["auditor"], [G1], True, False, False),
        (["platform-admin"], [], True, True, True),
        (["group-admin"], [], False, False, False),
        ([], [G1], False, False, False),
    ],
)
def test_capability_and_scope_are_independent(roles, groups, read, use, manage):
    async def check():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda request: httpx.Response(200, json=jwks()))
        ) as client:
            principal = await TokenVerifier(settings(), client).validate(
                signed(
                    claims(
                        resource_access={"proxylens-api": {"roles": roles}},
                        proxylens_group_ids=groups,
                    )
                )
            )
            assert principal.can(Capability.READ, G1) == read
            assert principal.can(Capability.USE, G1) == use
            assert principal.can(Capability.MANAGE, G1) == manage
            assert principal.can(Capability.MANAGE, G2) == ("platform-admin" in roles)

    asyncio.run(check())


def test_future_not_before_within_skew_but_expiry_has_no_grace():
    async def check():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda request: httpx.Response(200, json=jwks()))
        ) as client:
            verifier = TokenVerifier(settings(clock_skew=5), client)
            await verifier.validate(signed(claims(nbf=int(time.time()) + 2)))
            with pytest.raises(IdentityError):
                await verifier.validate(
                    signed(claims(exp=int(time.time()) - 1, iat=int(time.time()) - 200))
                )

    asyncio.run(check())


@pytest.mark.parametrize("response", [{"keys": []}, {"keys": [None]}, {}, {"keys": "bad"}])
def test_unusable_jwks_is_never_an_authentication_success(response):
    async def check():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda request: httpx.Response(200, json=response))
        ) as client:
            with pytest.raises(AuthorityUnavailable):
                await TokenVerifier(settings(), client).validate(signed())

    asyncio.run(check())


@pytest.mark.parametrize(
    "values",
    [
        {"redirect_uri": "http://public.example/oidc/callback"},
        {"redirect_uri": "https://api.example/wrong"},
        {"issuer": "https://identity.example/realms/wrong"},
        {"issuer": "http://public.example/realms/proxylens"},
        {"internal_url": "https://user:password@identity.example"},
        {"redirect_uri": "https://api.example/oidc/callback?next=evil"},
        {"jwks_ttl": 301},
        {"refresh_interval": 0},
        {"clock_skew": 31},
    ],
)
def test_invalid_identity_configuration_fails_at_startup(values):
    with pytest.raises(ValueError):
        IdentitySettings(**{"issuer": ISSUER, "internal_url": "https://identity.example", **values})


def test_failed_unknown_key_refresh_does_not_extend_cached_key_lifetime():
    now = [0.0]
    offline = [False]
    calls = []

    def handle(request):
        calls.append(request)
        if offline[0]:
            raise httpx.ReadTimeout("offline")
        return httpx.Response(200, json=jwks())

    async def check():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            verifier = TokenVerifier(settings(jwks_ttl=60), client, clock=lambda: now[0])
            await verifier.validate(signed())
            offline[0] = True
            now[0] = 20
            with pytest.raises(AuthorityUnavailable):
                await verifier.validate(signed(kid="unknown"))
            await verifier.validate(signed())
            now[0] = 60
            with pytest.raises(AuthorityUnavailable):
                await verifier.validate(signed())
            assert len(calls) == 3

    asyncio.run(check())
