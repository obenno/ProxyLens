# ProxyLens

Single-host integration for authorized subscription-backed API access, personal
usage visibility, and observability.

## Architecture transition

The revised candidate is **LiteLLM → CLIProxyAPI**, with native personal accounts,
user-owned keys and Usage, plus one native asynchronous Langfuse integration for
content-rich debugging traces. CPAMP becomes optional
operator diagnostics. Start with the [POC contract](docs/specs/litellm-poc.md) and
[issue revision record](docs/planning/architecture-rebaseline-2026-10-29.md).
Work is configuration-first: native setup, Langfuse configuration, one shared
integration acceptance pass, then deployment recovery/cutover. Advanced personal
charts and custom implementations require a demonstrated selected gap.

The [owner-approved tracing objective](docs/specs/litellm-poc.md#native-debugging-traces)
includes prompts/source code sent in requests, AI outputs, visible tool
names/arguments/results, useful errors and model/timing/tokens/estimated cost.
Use native configuration first, with targeted credential masking and verified
owner/session attribution. Native project access and retention govern trace
readers; `userId` filtering is analysis, not authorization. Unsent files/local
tool execution are outside gateway visibility; native fields may be missing or
truncated, and automatic removal of all embedded secrets is not promised.

The [candidate deployment record](docs/candidate/deployment.md#current-logging-settings-and-8-target)
preserves the original disabled-capture setup as history and records the active
#8 native callback configuration. Shared #7 A1–A6 acceptance remains the gate for
candidate acceptance; see [setup decisions](docs/candidate/decisions.md) for status.

[ADR 0002](docs/adr/0002-litellm-personal-usage.md) is **proposed**. The checked-in
runtime still implements [ADR 0001](docs/adr/0001-architecture-boundaries.md):
Keycloak, custom authorization/gateway, CPA and CPAMP-derived usage. Candidate
acceptance and approved cutover are separate milestones.

Start with `docs/deployment.md`. Verified image pins and upstream contracts are
in `docs/dependency-pins.md`; implementation decisions are in `DEVELOPMENT.md`.

## Current implemented scope

The original issue #2 scope provides a Compose stack and Python 3.12 service entrypoints:

```sh
PYTHONPATH=src .venv/bin/python -m proxylens api --port 8001
PYTHONPATH=src .venv/bin/python -m proxylens gateway --port 8000
PYTHONPATH=src .venv/bin/python -m proxylens worker --port 8002
```

Each process serves `/health/live` and `/health/ready`. The API exposes Keycloak
OIDC/resource management and proof-gated projection routes. The gateway exposes
the authorized Responses forwarding boundary. The worker owns projection polling,
completion scanning, retention, exporter recovery/drain, status checkpoints, and
group reconciliation. Tenant-scoped usage remains fail-closed until the reviewed
live correlation/history proof gate passes.

## Local checks

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install --require-hashes -r requirements-dev.lock
.venv/bin/python scripts/ci-tests.py  # locked zero-skip suite with PostgreSQL
.venv/bin/ruff check .
.venv/bin/ruff format --check .
bash -n deploy/keycloak/start.sh deploy/cliproxyapi/healthcheck.sh
```

The locked suite requires `PROXYLENS_CI_DATABASE_URL`; it creates isolated test
databases and needs `PROXYLENS_RECOVERY_PG_CONTAINER` plus
`PROXYLENS_RECOVERY_ENGINE` for the recovery checks. On a Docker host, also run
`docker compose config --quiet`, build, and the startup/restart/outage checks in
the deployment guide. Local tests cannot prove Docker networking, secret
permissions, or upstream interoperability.
