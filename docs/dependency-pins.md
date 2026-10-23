# Foundation dependency pins

Verified **2026-10-24**, against official release metadata, tagged source,
Docker Official Images metadata, PyPI, and registry manifest responses. These are
deliberate pins, not a claim that subsequent releases are compatible.

## Container artifacts

| Component | Version / image | Multi-platform manifest digest |
| --- | --- | --- |
| Python | `docker.io/library/python:3.12.15-slim-bookworm` | `sha256:6a0e06f5ba0b373d051aabd3fffb9b873f27f9a2a3a14bcbe37dee6f0e3bbc70` |
| PostgreSQL (both databases) | `docker.io/library/postgres:17.11-bookworm` | `sha256:858bb5e98eed02eb8cafbcdc007f9a65d1b613972028944a8ec2133ccaf80d27` |
| Keycloak | `quay.io/keycloak/keycloak:26.8.1` | `sha256:a78d6b79572168cb25886b80a8b5b8d4ed4390743e3eecb810538683e209dd6b` |
| CLIProxyAPI | `docker.io/eceasy/cli-proxy-api:v8.0.40` | `sha256:0a0ed62b20fa48ad9a5321cef1fbe98a6c02237827b04ee30ecceb8fb39b36e0` |
| CPAMP Full Mode | `ghcr.io/seakee/cpa-manager-plus:v1.14.9` | `sha256:c1641f4b1bc334241a38c8e66c641e250b725031f309f8131dabc419f0438ac0` |

`proxylens:0.1.0` is built locally from this checkout, the digest-pinned Python
base, and hash-locked requirements. Record the Git commit and resulting image ID
with each deployment; the local version tag alone does not identify the code.
No upstream image is selected with `latest` or a floating minor tag.

Official evidence (URLs retained here for reproducibility):

```text
https://github.com/docker-library/official-images/blob/master/library/python
https://github.com/docker-library/official-images/blob/master/library/postgres
https://github.com/keycloak/keycloak/releases/tag/26.8.1
https://github.com/router-for-me/CLIProxyAPI/releases/tag/v8.0.40
https://github.com/router-for-me/CLIProxyAPI/blob/v8.0.40/.github/workflows/docker-image.yml
https://github.com/seakee/CPA-Manager-Plus/releases/tag/v1.14.9
https://github.com/seakee/CPA-Manager-Plus/blob/v1.14.9/.github/workflows/release.yml
```

Registry manifests were fetched through Docker Hub, Quay, and GHCR's v2 APIs;
the `Docker-Content-Digest` response headers above were verified before use.
Tagged source confirms CPA publishes `eceasy/cli-proxy-api:v*`, while CPAMP
publishes its full Manager Server image to `ghcr.io/seakee/cpa-manager-plus:v*`.

Runtime smoke logs confirmed this CPAMP release polls CPA's supported legacy
`/v0/management/usage-queue` compatibility route. ProxyLens adds no consumer or
fallback collector. Future ProxyLens management adapters should use v8.

## Runtime contracts checked in tagged sources

| Contract | Official source |
| --- | --- |
| CPA v8 nested config, writable config/hash updates, OAuth directory, usage retention | `router-for-me/CLIProxyAPI@v8.0.40/config.example.yaml` |
| CPA executable path and Debian runtime (Bash available; no curl/wget assumed) | `router-for-me/CLIProxyAPI@v8.0.40/Dockerfile` |
| Nonconsumptive CPA `GET /healthz` | `router-for-me/CLIProxyAPI@v8.0.40/internal/api/server_routes.go` |
| CPAMP `CPA_UPSTREAM_URL`, key-file variables, `http` collector mode | `seakee/CPA-Manager-Plus@v1.14.9/apps/manager-server/internal/config/config.go` |
| CPAMP environment-backed connection bootstrap | `seakee/CPA-Manager-Plus@v1.14.9/apps/manager-server/internal/service/bootstrap/service.go` |
| CPAMP base64-encoded 32-byte data key | `seakee/CPA-Manager-Plus@v1.14.9/apps/manager-server/internal/security/security.go` |
| CPAMP `/data` persistence, `/health`, wget in image | `seakee/CPA-Manager-Plus@v1.14.9/docker-compose.manager.yml`, `Dockerfile.manager-server` |

Further first-party operational contracts:

```text
https://www.keycloak.org/server/containers
https://www.keycloak.org/server/importExport
https://www.keycloak.org/observability/health
https://docs.docker.com/compose/how-tos/use-secrets/
https://docs.docker.com/compose/how-tos/startup-order/
```

Keycloak startup import substitutes environment placeholders and skips an existing
realm. Its wrapper reads mounted secrets, exports them inside the container,
and `exec`s `kc.sh`; secrets are absent from Compose's environment configuration.
Health uses the private management listener on 9000. Realm/client bootstrap is
not identity/role-mapping completion.

## Python packages and tooling

`pyproject.toml` pins FastAPI 0.161.1, httpx 0.28.1, psycopg 3.3.6 (binary extra),
and Uvicorn 0.54.0. Test/lint dependencies: pytest 9.1.1, PyYAML 6.0.3,
Ruff 0.17.2. Versions were verified using each project's PyPI JSON metadata.
`requirements.lock` and `requirements-dev.lock` pin every resolved dependency
and distribution hash. Install with `--require-hashes`.

To intentionally refresh locks using `uv`:

```sh
uv pip compile pyproject.toml --generate-hashes -o requirements.lock
uv pip compile pyproject.toml --extra dev --generate-hashes -o requirements-dev.lock
```

Validation used the standalone official Docker Compose v5.6.1 CLI, SHA-256
`47737f4236e6d3ccea7291995203f8f018058783b4c3a9469119811a0b5db8c0`
(`docker-compose-linux-x86_64`, verified against GitHub release metadata).
Docker Engine is absent on the implementation host. See `DEVELOPMENT.md` for
the precise runtime validation performed and remaining limitations.

## Langfuse

Parent #1 permits an existing compatible local Langfuse deployment. This stack
accepts its base URL and mounted project credentials, without bundling Langfuse
or its databases. No dummy receiver is provided. Record that deployment's actual
version/digests and back up its PostgreSQL, ClickHouse, and object storage under
its own runbook before enabling the later exporter ticket.
## Identity extension pins (issue #5)

The Keycloak service now builds `deploy/keycloak/Dockerfile` on the existing
26.8.1 digest. The protocol mapper compiles against JARs copied directly from
that image; compiler base is `eclipse-temurin:21-jdk` pinned to manifest
`sha256:23cc5734ff46e776f51ce66eb9ee08444fd47caabec0a95b7eb6e94be2d3696d`.
No Maven dependency download is involved. Rebuild/retest the provider with every
Keycloak upgrade; its protocol-mapper SPI may change.

Python adds `PyJWT[crypto]==2.15.1`, confirmed available via PyPI JSON and actual
installation. Hash locks include cryptography 50.0.2 and its closure. Both runtime
and dev locks were regenerated using the existing uv compile commands.
