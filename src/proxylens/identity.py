"""Shared identity contracts. Only the Keycloak verifier creates trusted principals."""

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from fastapi import HTTPException, Request


class Capability(StrEnum):
    READ = "read"
    USE = "use"
    MANAGE = "manage"


class IdentityError(Exception):
    """Unverifiable credential. Never include upstream bodies or tokens in errors."""


class AuthorityUnavailable(Exception):
    """No current authoritative answer; must never be interpreted as deletion."""


class GroupState(StrEnum):
    ACTIVE = "active"
    MISSING = "missing"
    NESTED = "nested"


@dataclass(frozen=True)
class GroupEvidence:
    issuer: str
    group_id: str
    state: GroupState
    checked_at: float


class GroupAuthority(Protocol):
    async def lookup_group(self, group_id: str) -> GroupEvidence: ...

    async def require_available(self) -> None: ...


@dataclass(frozen=True)
class Principal:
    issuer: str
    subject: str
    roles: frozenset[str]
    group_ids: frozenset[str]
    expires_at: int
    verified_at: float
    signing_key_valid_until: float
    verification: str = "keycloak-rs256"

    @property
    def is_platform_admin(self) -> bool:
        return "platform-admin" in self.roles

    def has_capability(self, capability: Capability) -> bool:
        grants = {
            Capability.READ: {"platform-admin", "group-admin", "group-member", "auditor"},
            Capability.USE: {"platform-admin", "group-admin", "group-member"},
            Capability.MANAGE: {"platform-admin", "group-admin"},
        }
        return bool(self.roles & grants[capability])

    def in_scope(self, group_id: str) -> bool:
        return self.is_platform_admin or group_id in self.group_ids

    def can(self, capability: Capability, group_id: str) -> bool:
        return self.has_capability(capability) and self.in_scope(group_id)

    def require(self, capability: Capability, group_id: str) -> None:
        if not self.can(capability, group_id):
            raise HTTPException(403, "scope_denied")


async def require_group(
    principal: Principal, capability: Capability, group_id: str, authority: GroupAuthority
) -> None:
    """Scope first; writes/use additionally need live, flat, existing ownership."""
    principal.require(capability, group_id)
    if capability != Capability.READ:
        evidence = await authority.lookup_group(group_id)
        if evidence.state != GroupState.ACTIVE:
            raise HTTPException(403, "group_unusable")


async def get_principal(request: Request) -> Principal:
    """FastAPI dependency; API lifespan installs the identity service in app.state."""
    return await request.app.state.identity.authenticate(request)


def get_group_authority(request: Request) -> GroupAuthority:
    return request.app.state.identity.authority
