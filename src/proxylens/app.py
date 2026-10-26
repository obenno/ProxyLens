"""Service entrypoints, dependency health, and the API's Keycloak identity boundary."""

import asyncio
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import httpx
import psycopg
from fastapi import FastAPI
from fastapi.responses import JSONResponse

from proxylens.config import Settings, secret_file
from proxylens.cpamp import CollectorStatus, CPAMPAdapter
from proxylens.exporter_repository import ExportRepository
from proxylens.exporter_transport import OtlpTransport
from proxylens.exporter_worker import ExportWorker
from proxylens.gateway import Gateway, install_gateway_routes
from proxylens.identity import AuthorityUnavailable, get_principal
from proxylens.keycloak import KeycloakAuthority
from proxylens.oidc import IdentityService, install_identity_routes
from proxylens.operations import RetentionRunner
from proxylens.operations_health import ExportHealth, ProjectionHealth, operations_health
from proxylens.projection import ProjectionRepository, projection_worker_lifespan
from proxylens.projection_routes import install_projection_routes
from proxylens.resource_identity import RESOURCE_ACCESS, group_lookup
from proxylens.resource_routes import install_resource_routes
from proxylens.resources import ResourceRepository
from proxylens.runtime import (
    CompletionScanner,
    GatewayRetentionParticipant,
    OperationsSupervisor,
    OutboxRetentionParticipant,
    ProjectionRetentionParticipant,
    periodic_tick,
)


async def database_ready(settings: Settings) -> bool:
    try:
        async with asyncio.timeout(3):
            async with await psycopg.AsyncConnection.connect(
                host=settings.db_host,
                port=settings.db_port,
                dbname=settings.db_name,
                user=settings.db_user,
                password=secret_file(
                    "PROXYLENS_DB_PASSWORD_FILE", "/run/secrets/postgres_password"
                ),
                connect_timeout=2,
                options="-c statement_timeout=2000",
            ) as connection:
                await connection.execute("SELECT 1")
        return True
    except (OSError, ValueError, psycopg.Error, TimeoutError):
        return False


async def http_ready(url: str) -> bool:
    try:
        async with httpx.AsyncClient(timeout=2, trust_env=False) as client:
            response = await client.get(url)
            return response.status_code == 200
    except httpx.HTTPError:
        return False


async def group_authority_ready(settings: Settings) -> bool:
    try:
        async with httpx.AsyncClient(timeout=2, trust_env=False) as client:
            await KeycloakAuthority(settings.identity, client).require_available()
        return True
    except AuthorityUnavailable:
        return False


async def _worker_operations_health(app, settings, *, postgres, keycloak, cliproxyapi):
    """Build the redacted worker diagnostics from already-owned runtime seams."""
    runtime = getattr(app.state, "runtime", None)
    if runtime is None:
        return None

    now = datetime.now(UTC)
    projection = ProjectionHealth(enabled=True)
    try:
        projection_snapshot = await runtime.projection.health()
        last_success_ms = projection_snapshot.get("last_success_ms")
        projection = ProjectionHealth(
            enabled=True,
            last_success=(
                datetime.fromtimestamp(last_success_ms / 1000, UTC)
                if isinstance(last_success_ms, int)
                else None
            ),
            source_gap=(
                projection_snapshot.get("coverage") == "incomplete"
                or "retention_gap" in projection_snapshot.get("reasons", [])
            ),
            degraded=any(
                reason not in {"refresh_lag", "refresh_failed", "expected_usage_lag"}
                for reason in projection_snapshot.get("reasons", [])
            ),
        )
    except Exception:
        projection = ProjectionHealth(enabled=True)

    exporter = ExportHealth(enabled=runtime.scanner.exporter.settings.enabled)
    if exporter.enabled:
        try:
            stats = await runtime.scanner.exporter.stats(now=now)
            states = stats.get("states", {})
            pending = sum(
                states.get(name, 0) for name in ("WAITING", "READY", "RETRY_WAIT", "IN_FLIGHT")
            )
            oldest = stats.get("oldest_pending_seconds")
            exporter = ExportHealth(
                enabled=True,
                pending=pending,
                uncertain=states.get("UNCERTAIN", 0),
                dead_letters=states.get("DEAD_LETTER", 0),
                oldest_pending=(now - timedelta(seconds=oldest)) if oldest else None,
                available=True,
            )
        except Exception:
            exporter = ExportHealth(enabled=True, available=False)

    collector = runtime.supervisor.collector or CollectorStatus("unavailable", ("not_started",))
    return operations_health(
        now=now,
        postgres=postgres,
        keycloak=keycloak,
        cliproxyapi=cliproxyapi,
        adapter=runtime.adapter.health(),
        collector=collector,
        projection=projection,
        exporter=exporter,
    )


@dataclass(frozen=True)
class WorkerRuntime:
    adapter: CPAMPAdapter
    projection: ProjectionRepository
    scanner: CompletionScanner
    supervisor: OperationsSupervisor


def create_app(role: str, *, identity_transport: httpx.AsyncBaseTransport | None = None) -> FastAPI:
    if role not in {"api", "gateway", "worker"}:
        raise ValueError("role must be api, gateway, or worker")
    settings = Settings.from_environment()
    database = settings.database()

    async def lookup(group_id):
        return await group_lookup(app.state.identity.authority, settings.identity.issuer)(group_id)

    repository = ResourceRepository(database, lookup)
    projection_repository = ProjectionRepository(
        database, settings.projection, retention=settings.retention
    )
    proof_gate = settings.proof_gate()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await database.migrate()
        async with (
            httpx.AsyncClient(timeout=2, trust_env=False, transport=identity_transport) as client,
            httpx.AsyncClient(
                timeout=settings.gateway.idle_timeout, trust_env=False, follow_redirects=False
            ) as upstream,
        ):
            app.state.identity = IdentityService(settings.identity, client)
            app.state.database = database
            app.state.resources = repository
            app.state.projection = projection_repository
            if role == "gateway":
                app.state.gateway = Gateway(
                    database,
                    repository,
                    upstream,
                    settings.gateway,
                    issuer=settings.identity.issuer,
                    cpa_url=settings.cpa_url,
                )
            if role != "worker":
                yield
                return

            adapter = CPAMPAdapter(
                settings.cpamp_url,
                secret_file("PROXYLENS_CPAMP_ADMIN_KEY_FILE", "/run/secrets/cpamp_admin_key"),
                instance_id=settings.projection.cpamp_instance_id,
                stale_after_ms=settings.projection.stale_after_ms,
            )
            exporter_repository = ExportRepository(
                database, settings.exporter, retention=settings.retention
            )
            exporter_worker = ExportWorker(
                exporter_repository,
                OtlpTransport(settings.exporter),
            )
            scanner = CompletionScanner(
                database,
                settings.projection,
                exporter_repository,
                gate=proof_gate,
                retention=settings.retention,
                pending_timeout_seconds=settings.completion_pending_seconds,
            )
            retention = RetentionRunner(
                database,
                settings.retention,
                (
                    GatewayRetentionParticipant(),
                    ProjectionRetentionParticipant(),
                    OutboxRetentionParticipant(exporter_repository),
                ),
            )
            supervisor = OperationsSupervisor(
                adapter=adapter,
                projection=projection_repository,
                scanner=scanner,
                exporter=exporter_worker,
                retention=retention,
                interval_seconds=settings.worker_interval_seconds,
                retention_interval_seconds=settings.retention_interval_seconds,
                scan_limit=settings.worker_scan_limit,
                drain_limit=settings.worker_drain_limit,
            )
            app.state.adapter = adapter
            app.state.exporter = exporter_repository
            app.state.scanner = scanner
            app.state.supervisor = supervisor
            app.state.runtime = WorkerRuntime(
                adapter=adapter,
                projection=projection_repository,
                scanner=scanner,
                supervisor=supervisor,
            )

            async def reconcile_groups():
                async with database.transaction() as conn:
                    rows = await (
                        await conn.execute("SELECT id FROM resource_group_refs ORDER BY id")
                    ).fetchall()
                group_ids = [row["id"] for row in rows]

                async def mark_unusable(evidence):
                    await repository.reconcile_group(evidence.group_id, actor="worker")

                await app.state.identity.authority.reconcile(group_ids, mark_unusable)

            async def checkpoint_status():
                async with database.transaction() as conn:
                    for component, state in supervisor.status.items():
                        await conn.execute(
                            "INSERT INTO operations_status(component, observed_at, state, details) "
                            "VALUES (%s, clock_timestamp(), %s, %s) "
                            "ON CONFLICT(component) DO UPDATE SET "
                            "observed_at=EXCLUDED.observed_at, "
                            "state=EXCLUDED.state, details=EXCLUDED.details",
                            (component, state["state"], {}),
                        )

            async with projection_worker_lifespan(projection_repository, adapter, gate=proof_gate):
                stop = asyncio.Event()
                supervisor_task = asyncio.create_task(
                    supervisor.run(stop), name="operations-supervisor"
                )
                reconcile_task = asyncio.create_task(
                    periodic_tick(
                        stop,
                        settings.group_reconcile_interval_seconds,
                        reconcile_groups,
                        name="group_reconcile",
                        status=supervisor.status,
                    ),
                    name="group-reconciliation",
                )
                status_task = asyncio.create_task(
                    periodic_tick(
                        stop,
                        settings.worker_interval_seconds,
                        checkpoint_status,
                        name="status_checkpoint",
                        status=supervisor.status,
                    ),
                    name="status-checkpoint",
                )
                await checkpoint_status()
                try:
                    yield
                finally:
                    stop.set()
                    for task in (supervisor_task, reconcile_task, status_task):
                        task.cancel()
                    for task in (supervisor_task, reconcile_task, status_task):
                        with suppress(asyncio.CancelledError):
                            await task

    app = FastAPI(
        title=f"ProxyLens {role}",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )
    if role == "api":
        install_identity_routes(app)
        install_resource_routes(
            app, repository, principal_dependency=get_principal, access=RESOURCE_ACCESS
        )
        install_projection_routes(app, projection_repository, gate=proof_gate)
    if role == "gateway":
        install_gateway_routes(app)

    @app.get("/health/live")
    async def live():
        return {"status": "live", "role": role, "stage": "runtime"}

    @app.get("/health/ready")
    async def ready():
        probes = {"postgres": database_ready(settings)}
        if role in {"api", "gateway"}:
            probes["keycloak"] = http_ready(
                f"{settings.keycloak_url}/realms/proxylens/.well-known/openid-configuration"
            )
        if role in {"api", "gateway"}:
            probes["keycloak_group_authority"] = group_authority_ready(settings)
        if role == "gateway":
            probes["cliproxyapi"] = http_ready(f"{settings.cpa_url}/healthz")
        if role == "worker":
            probes["keycloak_group_authority"] = group_authority_ready(settings)
            probes["cliproxyapi"] = http_ready(f"{settings.cpa_url}/healthz")
            probes["cpamp"] = http_ready(f"{settings.cpamp_url}/health")
        results = await asyncio.gather(*probes.values())
        dependencies = dict(
            zip(probes, ("ready" if ok else "unavailable" for ok in results), strict=True)
        )
        if role == "gateway":
            gateway = getattr(app.state, "gateway", None)
            dependencies["gateway_metadata"] = (
                "unavailable"
                if gateway is None
                else "degraded"
                if gateway.metadata_failures
                else "ready"
            )
            results.append(gateway is not None and not gateway.metadata_failures)
        operations = None
        if role == "worker":
            operations = await _worker_operations_health(
                app,
                settings,
                postgres=dependencies.get("postgres") == "ready",
                keycloak=dependencies.get("keycloak_group_authority") == "ready",
                cliproxyapi=dependencies.get("cliproxyapi") == "ready",
            )
        return JSONResponse(
            status_code=200 if all(results) else 503,
            content={
                "status": "ready" if all(results) else "unavailable",
                "role": role,
                "stage": "runtime",
                "dependencies": dependencies,
                **({"operations": operations} if operations is not None else {}),
            },
        )

    return app
