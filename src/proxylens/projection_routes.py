"""Install gated usage endpoints with the real Keycloak principal dependency."""

from uuid import UUID

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute

from proxylens.db import StorageUnavailable
from proxylens.identity import AuthorityUnavailable, IdentityError, get_principal
from proxylens.projection import ProjectionRepository
from proxylens.projection_settings import DISABLED_PROOF_GATE, ProofGate


def install_projection_routes(
    app: FastAPI,
    repository: ProjectionRepository,
    *,
    gate: ProofGate = DISABLED_PROOF_GATE,
) -> APIRouter:
    """Identity lifespan must install app.state.identity; no alternate principal adapter."""

    class UsageRoute(APIRoute):
        def get_route_handler(self):
            original = super().get_route_handler()

            async def handle(request):
                try:
                    response = await original(request)
                except IdentityError:
                    response = JSONResponse({"error": "unauthenticated"}, status_code=401)
                except (StorageUnavailable, AuthorityUnavailable):
                    response = JSONResponse({"error": "dependency_unavailable"}, status_code=503)
                except HTTPException as error:
                    response = JSONResponse({"error": error.detail}, status_code=error.status_code)
                response.headers["Cache-Control"] = "no-store"
                return response

            return handle

    router = APIRouter(prefix="/api", route_class=UsageRoute)

    identity_dependency = Depends(get_principal)

    async def access(principal=identity_dependency):
        if not gate.permits(repository.settings):
            raise HTTPException(503, "tenant_usage_disabled")
        return principal

    access_dependency = Depends(access)

    async def usage_query(
        group_id: str | None = None,
        application_id: UUID | None = None,
        from_ms: int | None = Query(None, ge=1),
        to_ms: int | None = Query(None, ge=1),
        limit: int = Query(100, ge=1, le=200),
        offset: int = Query(0, ge=0),
        principal=access_dependency,
    ):
        result = await repository.query(
            principal,
            group_id=group_id,
            application_id=str(application_id) if application_id else None,
            from_ms=from_ms,
            to_ms=to_ms,
            limit=limit,
            offset=offset,
        )
        # Global retention/duplicate counts are operator diagnostics, never tenant data.
        health = await repository.health()
        result["health"] = {
            key: health[key]
            for key in (
                "state",
                "last_success_ms",
                "coverage",
                "source_watermark_ms",
            )
        }
        return result

    query_dependency = Depends(usage_query)

    @router.get("/usage")
    async def usage(result=query_dependency):
        return result

    @router.get("/usage/totals")
    async def totals(result=query_dependency):
        return {**result["totals"], "coverage": result["coverage"], "health": result["health"]}

    @router.get("/groups/{group_id}/usage")
    async def group_usage(result=query_dependency):
        return result

    @router.get("/applications/{application_id}/usage")
    async def application_usage(result=query_dependency):
        return result

    @router.get("/usage/records/{event_hash}")
    async def record(event_hash: str, principal=access_dependency):
        result = await repository.query(principal, event_hash=event_hash)
        if not result["records"]:
            raise HTTPException(404, "not_found")
        return result["records"][0]

    app.include_router(router)
    return router
