"""Adapters from verified Keycloak contracts to resource authorization."""

from proxylens.identity import AuthorityUnavailable, Capability, GroupAuthority, GroupState
from proxylens.resource_routes import ResourceAccess
from proxylens.resources import VerifiedGroup

RESOURCE_ACCESS = ResourceAccess(
    actor=lambda p: p.subject,
    read_groups=lambda p: p.group_ids if p.has_capability(Capability.READ) else frozenset(),
    can_manage=lambda p, group: p.can(Capability.MANAGE, group),
    is_platform_admin=lambda p: p.is_platform_admin,
    can_audit=lambda p: bool(p.roles & {"auditor", "group-admin"}),
)


def group_lookup(authority: GroupAuthority, issuer: str):
    async def lookup(group_id: str) -> VerifiedGroup | None:
        evidence = await authority.lookup_group(group_id)
        if evidence.issuer != issuer or evidence.group_id != group_id:
            raise AuthorityUnavailable("group_authority_unavailable")
        if evidence.state == GroupState.MISSING:
            return None
        if evidence.state != GroupState.ACTIVE:
            raise AuthorityUnavailable("group_unusable")
        return VerifiedGroup(group_id)

    return lookup
