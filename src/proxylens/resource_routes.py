"""Scoped control-plane routes; identity verification is supplied by issue #5."""

from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict, Field

from proxylens.db import StorageUnavailable
from proxylens.identity import IdentityError
from proxylens.policies import Policy
from proxylens.resources import ResourceError, ResourceRepository


@dataclass(frozen=True)
class ResourceAccess:
    """Adapters over a verified identity Principal, never over HTTP body claims.

    None from read_groups means platform-wide; an empty set grants no scope.
    Identity owns group-role mapping. Platform capability is checked separately.
    """

    actor: Callable
    read_groups: Callable
    can_manage: Callable
    is_platform_admin: Callable
    can_audit: Callable = lambda _: False


class ApplicationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    group_id: str = Field(min_length=1, max_length=200)
    name: str = Field(min_length=1, max_length=200)


class KeyCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expires_at: datetime | None = None


class Reassignment(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target_group_id: str = Field(min_length=1, max_length=200)


def install_resource_routes(
    app: FastAPI,
    repository: ResourceRepository,
    *,
    principal_dependency: Callable,
    access: ResourceAccess,
) -> APIRouter:
    """Install after identity startup; does not mutate app config/lifespan or verify JWTs."""

    class AuditedRoute(APIRoute):
        def get_route_handler(self):
            original = super().get_route_handler()

            async def handle(request):
                try:
                    response = await original(request)
                except StorageUnavailable:
                    response = JSONResponse(
                        status_code=503, content={"error": "storage_unavailable"}
                    )
                except IdentityError:
                    try:
                        await repository.record_denial(
                            "management.denied",
                            actor=getattr(request.state, "resource_actor", None),
                            group_id=getattr(request.state, "resource_group", None),
                            resource_id=getattr(request.state, "resource_id", None),
                            code="unauthenticated",
                        )
                    except StorageUnavailable:
                        response = JSONResponse(
                            status_code=503, content={"error": "storage_unavailable"}
                        )
                    else:
                        response = JSONResponse(
                            status_code=401, content={"error": "unauthenticated"}
                        )
                except (ResourceError, HTTPException) as error:
                    status = error.status if isinstance(error, ResourceError) else error.status_code
                    code = (
                        error.code
                        if isinstance(error, ResourceError)
                        else "unauthenticated"
                        if status == 401
                        else "forbidden"
                    )
                    if status in {401, 403, 404, 409}:
                        try:
                            await repository.record_denial(
                                "management.denied",
                                actor=getattr(request.state, "resource_actor", None),
                                group_id=getattr(request.state, "resource_group", None),
                                resource_id=getattr(request.state, "resource_id", None),
                                code=code,
                            )
                        except StorageUnavailable:
                            status, code = 503, "storage_unavailable"
                    response = JSONResponse(status_code=status, content={"error": code})
                response.headers["Cache-Control"] = "no-store"
                return response

            return handle

    router = APIRouter(prefix="/api", route_class=AuditedRoute)

    async def principal(request: Request, verified: Annotated[Any, Depends(principal_dependency)]):
        request.state.resource_actor = access.actor(verified)
        return verified

    principal_dep = Depends(principal)

    def scope(request, p, group_id, *, manage=False, platform=False, resource_id=None):
        request.state.resource_group = group_id
        request.state.resource_id = resource_id
        if access.is_platform_admin(p):
            return
        if platform:
            raise ResourceError("forbidden", 403)
        if manage:
            if not access.can_manage(p, group_id):
                raise ResourceError("forbidden", 403)
        elif group_id not in (access.read_groups(p) or set()):
            raise ResourceError("not_found", 404)

    async def application(request, p, application_id, *, manage=False, platform=False):
        found = await repository.get_application(str(application_id))
        scope(
            request, p, found["group_id"], manage=manage, platform=platform, resource_id=found["id"]
        )
        return found

    @router.post("/applications", status_code=201)
    async def create_application(body: ApplicationCreate, request: Request, p=principal_dep):
        scope(request, p, body.group_id, manage=True)
        return await repository.create_application(body.group_id, body.name, actor=access.actor(p))

    @router.get("/applications")
    async def list_applications(
        request: Request,
        group_id: str | None = None,
        limit: int = Query(100, ge=1, le=200),
        offset: int = Query(0, ge=0),
        p=principal_dep,
    ):
        groups = None if access.is_platform_admin(p) else set(access.read_groups(p) or ())
        if group_id is not None:
            scope(request, p, group_id)
            groups = {group_id}
        return await repository.list_applications(groups, limit=limit, offset=offset)

    @router.get("/applications/{application_id}")
    async def get_application(application_id: UUID, request: Request, p=principal_dep):
        return await application(request, p, application_id)

    @router.get("/applications/{application_id}/keys")
    async def list_keys(application_id: UUID, request: Request, p=principal_dep):
        await application(request, p, application_id)
        return await repository.list_keys(str(application_id))

    @router.post("/applications/{application_id}/keys", status_code=201)
    async def create_key(application_id: UUID, body: KeyCreate, request: Request, p=principal_dep):
        await application(request, p, application_id, manage=True)
        issued = await repository.create_key(
            str(application_id), actor=access.actor(p), expires_at=body.expires_at
        )
        return {"key": issued.key, "plaintext": issued.plaintext}

    @router.post("/applications/{application_id}/keys/{key_id}/rotate", status_code=201)
    async def rotate_key(
        application_id: UUID, key_id: UUID, body: KeyCreate, request: Request, p=principal_dep
    ):
        await application(request, p, application_id, manage=True)
        request.state.resource_id = str(key_id)
        issued = await repository.rotate_key(
            str(application_id), str(key_id), actor=access.actor(p), expires_at=body.expires_at
        )
        return {"key": issued.key, "plaintext": issued.plaintext}

    @router.post("/applications/{application_id}/keys/{key_id}/revoke")
    async def revoke_key(application_id: UUID, key_id: UUID, request: Request, p=principal_dep):
        await application(request, p, application_id, manage=True)
        request.state.resource_id = str(key_id)
        return await repository.revoke_key(str(application_id), str(key_id), actor=access.actor(p))

    @router.put("/groups/{group_id}/policy")
    async def group_policy(group_id: str, body: Policy, request: Request, p=principal_dep):
        scope(request, p, group_id, manage=True, resource_id=group_id)
        return await repository.set_group_policy(group_id, body, actor=access.actor(p))

    @router.put("/applications/{application_id}/policy")
    async def application_policy(
        application_id: UUID, body: Policy, request: Request, p=principal_dep
    ):
        await application(request, p, application_id, manage=True)
        return asdict(
            await repository.set_application_policy(
                str(application_id), body, actor=access.actor(p)
            )
        )

    @router.get("/applications/{application_id}/effective-policy")
    async def get_policy(application_id: UUID, request: Request, p=principal_dep):
        await application(request, p, application_id)
        return asdict(await repository.effective_policy(str(application_id)))

    @router.post("/groups/{group_id}/reconcile")
    async def reconcile(group_id: str, request: Request, p=principal_dep):
        scope(request, p, group_id, platform=True, resource_id=group_id)
        return await repository.reconcile_group(group_id, actor=access.actor(p))

    @router.post("/applications/{application_id}/revoke")
    async def revoke_application(application_id: UUID, request: Request, p=principal_dep):
        await application(request, p, application_id, manage=True)
        return await repository.revoke_application(str(application_id), actor=access.actor(p))

    @router.post("/applications/{application_id}/reassign", status_code=201)
    async def reassign(application_id: UUID, body: Reassignment, request: Request, p=principal_dep):
        await application(request, p, application_id, platform=True)
        return await repository.reassign_orphan(
            str(application_id), body.target_group_id, actor=access.actor(p)
        )

    @router.get("/resource-audit")
    async def audit(
        request: Request,
        group_id: str | None = None,
        limit: int = Query(100, ge=1, le=200),
        offset: int = Query(0, ge=0),
        p=principal_dep,
    ):
        if not access.is_platform_admin(p) and not access.can_audit(p):
            raise ResourceError("forbidden", 403)
        groups = None if access.is_platform_admin(p) else set(access.read_groups(p) or ())
        if group_id is not None:
            scope(request, p, group_id)
            groups = {group_id}
        return await repository.list_audit(groups, limit=limit, offset=offset)

    app.include_router(router)
    return router
