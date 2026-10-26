# ProxyLens

Single-host integration foundation for Keycloak identity, CLIProxyAPI provider
access, CPAMP Full Mode usage history, and ProxyLens resource authorization.

Start with `docs/deployment.md`. Verified image pins and upstream contracts are
in `docs/dependency-pins.md`; implementation decisions are in `DEVELOPMENT.md`.

## Current scope

Issue #2 provides a Compose stack and Python 3.12 service entrypoints:

```sh
PYTHONPATH=src .venv/bin/python -m proxylens api
PYTHONPATH=src .venv/bin/python -m proxylens gateway --port 8001
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
