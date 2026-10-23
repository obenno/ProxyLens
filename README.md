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

Each process serves `/health/live` and `/health/ready`. The worker currently
exposes only its private health server; background jobs are added by later issues.
All business/model routes return 404. Identity validation, client keys, forwarding,
CPAMP projections, correlation, and Langfuse export are Phase 1 follow-up work.

## Local checks (no container engine required)

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install --require-hashes -r requirements-dev.lock
.venv/bin/python -m pytest -q
.venv/bin/ruff check .
.venv/bin/ruff format --check .
bash -n deploy/keycloak/start.sh deploy/cliproxyapi/healthcheck.sh
```

On a Docker host, also run `docker compose config --quiet`, build, and the
startup/restart/outage checks in the deployment guide. Local configuration tests
cannot prove Docker networking, secret permissions, or upstream interoperability.
