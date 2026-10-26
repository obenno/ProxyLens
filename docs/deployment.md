# Single-host foundation deployment

This includes issue #2's foundation and issue #5's Keycloak identity boundary.
API supports OIDC login and `/api/me`; a healthy stack does **not** mean the
Phase 1 POC is complete. See `docs/identity.md` for clients, role/scope rules,
existing-realm migration and the bounded token-validation outage policy.

## Prerequisites and setup

Use a Linux host with Docker Engine, the Docker Compose plugin (standalone v5.6.1
was used for configuration validation), Git, Python 3.12, and registry access.
Both amd64 and arm64 image manifests are published; this change's supplemental
runtime checks used amd64 only. Provision storage for both PostgreSQL instances,
CPAMP history, CPA credentials/config, and backups. Keycloak is capped at 2 GiB;
this is a POC resource bound, not a sizing claim.

From the repository root:

```sh
cp .env.example .env
python3 scripts/init-secrets.py
docker compose config --quiet
docker compose pull --ignore-buildable
docker compose build
docker compose up -d --wait --wait-timeout 240
docker compose ps -a
curl --fail http://localhost:8000/health/ready
curl --fail http://localhost:8001/health/ready
curl --fail http://localhost:8080/realms/proxylens/.well-known/openid-configuration
docker compose exec worker python -m proxylens healthcheck
```

The initializer exits successfully; all other services should become healthy.
`docker compose config --quiet` validates syntax without rendering secret contents.
If ports change, update the matching public URLs in `.env` before startup.

### Published listeners

| Listener | Default host bind | Purpose |
| --- | --- | --- |
| Gateway | `127.0.0.1:8000` | Authorized Responses forwarding and health |
| ProxyLens API | `127.0.0.1:8001` | OIDC, resource management, proof-gated projection reads, and health |
| Keycloak | `127.0.0.1:8080` | Human login and administrator console |

CLIProxyAPI `8317`, CPAMP `18317`, both database `5432` listeners, Keycloak
management `9000`, and worker health `8000` have **no host port publication**.
Backend, identity, and provider networks are internal. Edge networking supports
the three approved host listeners; egress networking lets CPA reach providers,
CPAMP reach its documented metadata services, and the worker reach the configured
Langfuse endpoint. These networks are connectivity boundaries, not
path-level firewalls: CPA client and management APIs share one internal listener.
Only CPA initialization and CPAMP receive the management key.

For remote access, place an operator-managed TLS ingress in front of the approved
listeners and set `KEYCLOAK_PUBLIC_URL` and the exact `PROXYLENS_REDIRECT_URI`.
The reference configuration is loopback HTTP; do not publish the private ports
to bypass future authorization. Configure trusted proxy headers deliberately
when adding an ingress. The foundation does not include a TLS proxy.

### Secrets and first boot

`scripts/init-secrets.py` uses the standard library, generates independent keys,
and preserves existing files on rerun. CPAMP's encryption key is base64 of 32
random bytes. Langfuse files start empty because invented credentials are invalid.

`secrets/` has mode 0700. Files have mode 0644 so Docker's file-backed secret binds
are readable by nonroot container users (Keycloak and ProxyLens); the parent
directory prevents traversal by other host users. Compose cannot reliably apply
`uid`/`gid`/`mode` overrides to these local file binds. Keep this directory private
and back it up encrypted. Host root and the container-engine administrator can
read these values. No secret is interpolated into `compose.yaml` or `.env`.

Keycloak imports one `proxylens` realm with separate public browser PKCE,
API-audience and confidential read-only Admin clients. The custom pinned image
includes the stable group-ID mapper. Sign in to its admin console as `admin`, using
`secrets/keycloak_admin_password`; create a permanent operator account and remove
the temporary bootstrap account. Create human users/flat groups and assign
`proxylens-api` roles in Keycloak; no test users/groups are seeded.
Keycloak persists realm, users, and sessions in `keycloak_db_data`. The import
JSON is only a first-boot seed; restarting skips an existing realm.

`cpa-init` seeds `cpa_config:/config/config.yaml` from the v8 template and mounted
keys only if no config exists. JSON input is valid YAML; CPA rewrites and hashes
the management key in its writable config. Operator changes persist across
restarts. OAuth credentials live in `cpa_auth`. Raw request logging and the
downloaded CPA panel are disabled. No provider is logged in by this ticket.

CPAMP bootstraps the CPA connection from its URL and mounted management key,
uses its real Full Mode SQLite database under `/data`, and is the **only** usage
queue consumer. `USAGE_COLLECTOR_MODE=http` selects the supported HTTP transport.
Never probe the consumptive usage queue to test health. CPA `/healthz` and CPAMP
`/health` are safe probes. CPAMP health alone does not establish collector freshness.

### Private operator access

Use `docker compose exec` for diagnostics. The CPAMP manager key never belongs in
an end-user browser or ProxyLens response. CPAMP's UI/API remains private even to
the default host network. If an operator explicitly needs its UI, tunnel it
through a **temporary loopback-only relay** in a separately reviewed deployment
override; do not add a permanent host mapping to the reference stack. Normal
foundation verification needs only `/health` from inside its container:

```sh
docker compose exec cpamp wget -qO- http://127.0.0.1:18317/health
docker compose exec cliproxyapi /bin/bash /healthcheck.sh
docker compose logs --tail 50 cpamp
```

### Langfuse endpoint contract

Parent #1 permits an existing compatible local Langfuse deployment. Set
`LANGFUSE_BASE_URL` to that real deployment (for example,
`http://host.docker.internal:3000`), and put its real project public/secret keys in
`secrets/langfuse_public_key` and `secrets/langfuse_secret_key`. Keep the secret
directory and file permissions described above. The worker has the Linux
`host-gateway` alias; the host service must listen on an address reachable from
containers, not exclusively host loopback. Alternatively use a reachable local
hostname. Use its root base URL, not an invented ingestion route.

Empty URL means unconfigured; the worker then keeps export disabled. When
configured, Langfuse credentials are mounted only to the worker, which owns the
metadata-only outbox, bounded delivery/recovery, retry uncertainty, and redacted
dependency-state reporting. Existing Langfuse state must have its own persistent
storage and backup/restore runbook.

## Persistent state and rotation

| Named volume | Authoritative contents | Restore dependency |
| --- | --- | --- |
| `postgres_data` | ProxyLens resources; later rebuildable usage projections | Matching DB credentials and application code |
| `keycloak_db_data` | Keycloak identities, groups, realm, clients, sessions | Matching Keycloak version and client secret |
| `cpa_config` | CPA settings, service access key, hashed management key | Matching secret files and CPA version |
| `cpa_auth` | Provider OAuth credentials | Provider may still require reauthorization |
| `cpamp_data` | Authoritative request history, manager config, archives | **Matching `cpamp_data_key`** and manager credentials |

Default volume names are prefixed `proxylens_`. Keep a stable Compose project name;
changing it creates a fresh set of volumes and can look like data loss.

Changing secret files does not rotate persisted credentials automatically:

- PostgreSQL passwords are initialization-only; change database roles and mounted
  values together, then recreate dependent containers.
- Keycloak bootstrap passwords and realm import client secrets are initialization-
  only; rotate through Keycloak and update the corresponding mounted files.
- CPA config is intentionally preserved. Rotate its management/client keys through
  the supported management interface and update CPAMP/gateway secret mounts together.
- CPAMP stores its connection/config; verify its effective connection after rotation.
  Preserve its data key unless using an upstream-supported re-encryption migration.
- Recreate affected containers after replacing a secret file; bind mounts can retain
  the old inode. A plain application restart is not sufficient evidence of rotation.

## Backup: quiesced, matching recovery set

The following cold backup is the simplest coherent foundation snapshot. The
controlled recovery workflow in `docs/operations.md` and `scripts/recovery.py` is
preferred; the commands below are a legacy manual equivalent for maintenance
windows where that workflow is unavailable. Commands assume the default project
name. Run in Bash from the checkout; preserve the same shell's `BACKUP` variable.
It deliberately stops traffic and database writers.
Once forwarding exists, first close ingress, wait for in-flight requests, and allow
CPAMP to drain while CPA is still running. CPA's in-memory queue is not backed up.

```sh
umask 077
BACKUP="$PWD/backups/$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "$BACKUP"
docker compose stop gateway api worker
# After confirming the collector is caught up, stop both provider services.
docker compose stop cpamp cliproxyapi keycloak
docker compose stop postgres keycloak-db
git rev-parse HEAD > "$BACKUP/git-commit.txt"
docker compose config --images > "$BACKUP/images.txt"
cp .env "$BACKUP/environment"
tar -czf "$BACKUP/secrets.tgz" secrets
for volume in postgres_data keycloak_db_data cpa_config cpa_auth cpamp_data; do
  docker run --rm --network none --user 0 \
    -v "proxylens_${volume}:/source:ro" \
    -v "$BACKUP:/backup" \
    --entrypoint tar \
    docker.io/library/postgres:17.11-bookworm@sha256:858bb5e98eed02eb8cafbcdc007f9a65d1b613972028944a8ec2133ccaf80d27 \
    -czpf "/backup/${volume}.tgz" -C /source .
done
sha256sum "$BACKUP"/*.tgz > "$BACKUP/SHA256SUMS"
docker compose up -d --wait --wait-timeout 240
```

Check every command's exit status; do not continue a failed backup as a valid set.
Encrypt and copy the completed recovery set off-host, preserving a repository
bundle or access to the recorded Git commit and pinned image artifacts. If
Langfuse is enabled externally, coordinate its backups with its operator.
Do not copy a live SQLite file without its WAL: stopping CPAMP and archiving its
whole data volume avoids that error. Do not copy a live PostgreSQL data directory.

## Restore

1. Use an isolated replacement host or an isolated Compose project. Check archive
   hashes and obtain the **exact recorded checkout and image pins**. Stop any
   existing services. Never unpack this backup over a populated running database.
2. Restore `.env` and `secrets/` from the matching set; ensure `secrets/` is 0700
   and secret files are 0644. Use the backup's CPA and CPAMP keys, not new random keys.
3. Create **empty** volumes, then restore every archive with numeric ownership:

   ```sh
   # Set BACKUP to the absolute verified backup path first.
   for volume in postgres_data keycloak_db_data cpa_config cpa_auth cpamp_data; do
     docker volume create "proxylens_${volume}"
     docker run --rm --network none --user 0 \
       -v "proxylens_${volume}:/target" -v "$BACKUP:/backup:ro" \
       --entrypoint tar \
       docker.io/library/postgres:17.11-bookworm@sha256:858bb5e98eed02eb8cafbcdc007f9a65d1b613972028944a8ec2133ccaf80d27 \
       --numeric-owner -xzpf "/backup/${volume}.tgz" -C /target
   done
   ```

   `docker volume create` also succeeds for an existing volume: explicitly verify
   that the destination volumes are empty before extraction. Prefer a fresh host.
4. Start storage first: `docker compose up -d --wait postgres keycloak-db`.
5. Start identity/provider: `docker compose up -d --wait keycloak cliproxyapi`.
   CPA initializer preserves the restored config; Keycloak skips the existing realm.
6. Start CPAMP: `docker compose up -d --wait cpamp`; check history availability and
   collector health using its supported APIs without popping the CPA queue manually.
7. Start the application: `docker compose up -d --wait api gateway worker`.
   Verify health, issuer, stored resources/history, and provider credential validity
   before reopening ingress. Rebuild projections only after the read/correlation
   adapter is validated. Restore Langfuse separately under its versioned runbook.

Cold PostgreSQL archives require compatible architecture and the same major/server
storage format. For cross-major or cross-platform migration use PostgreSQL's
documented logical dump/restore or upgrade workflow, not this physical-copy recipe.
Test recovery on an isolated host before relying on these archives.

## Upgrade and rollback order

1. Record current Git commit, image IDs/digests, dependency locks, and upstream
   release notes. Verify new official tags/digests and update
   `docs/dependency-pins.md` together with Compose/Dockerfile pins.
2. Take a matching quiesced recovery set. Rehearse on an isolated restore. Check
   CPA/CPAMP API compatibility and Keycloak/PostgreSQL schema requirements first.
3. Stop gateway/API/worker, then CPAMP/CPA/Keycloak. Upgrade databases first only
   if required using their supported migration path. Wait for both to be healthy.
4. Upgrade Keycloak and verify discovery/login. Upgrade CPA then CPAMP as a tested
   pair; verify preserved credentials, collector operation, and durable history.
5. Build/recreate API/gateway/worker; rerun health, restart, and outage checks.
   Reopen ingress after the ticket's integration gates pass. Coordinate an external
   Langfuse upgrade separately so it never becomes a forwarding dependency.
6. On failure, stop the new writers. Restore the **entire pre-upgrade recovery set**
   with its old code, images, secrets, and volumes. Do not point old Keycloak/CPAMP
   binaries at migrated databases unless upstream explicitly supports downgrade.
   Rollback loses writes made after the snapshot; record that interval. Reverify
   storage → identity/CPA → CPAMP → application before reopening ingress.

`docker compose down` preserves named volumes. `docker compose down -v` destroys
them and is not a routine restart or rollback command.

## Dependency outages and verification

Health semantics are deliberately narrow: `/health/live` says the process serves
HTTP; `/health/ready` checks a real PostgreSQL `SELECT 1` plus role dependencies,
in parallel with bounded timeouts. Errors become fixed `unavailable` labels,
without credentials, exception bodies, or internal URLs. Neither endpoint is an
authorization decision. Unknown routes remain 404; authorized routes still enforce
their own identity, policy, and proof gates.

| Dependency unavailable | Foundation behavior | Recovery / data consequence |
| --- | --- | --- |
| ProxyLens PostgreSQL | API/gateway/worker ready=503, live=200 | Restore DB; probes recover automatically. Later authorization must fail closed. |
| Keycloak or its DB | API/gateway ready=503 | Cached-key, unexpired-token reads only; new login/management fail closed; see `docs/identity.md`. |
| CPA | Gateway ready=503; CPAMP may remain HTTP-healthy | Restore CPA; inspect collector. In-memory queue is lost on CPA restart. |
| CPAMP | Worker ready=503; API/gateway health unaffected | CPA queues only in memory, configured retention 3600s. Collector downtime beyond retention or CPA restart can lose records. No replay guarantee. |
| Langfuse | Disabled when URL is empty; otherwise asynchronous worker export | Provider forwarding remains independent; inspect worker backlog, uncertainty, and dead letters. |

Long-form `depends_on` gates initial startup. It does not stop dependent services
when a dependency fails later. `restart: unless-stopped` restarts exited processes,
not merely unhealthy ones. Monitor health and collector freshness separately.

On an isolated test deployment, record health, stop each dependency, confirm the
table, restart it, and confirm automatic recovery. For example:

```sh
docker compose stop cpamp
curl --fail http://localhost:8000/health/ready
# Expected nonzero while CPAMP is stopped:
docker compose exec worker python -m proxylens healthcheck
docker compose start cpamp
docker compose up -d --wait --wait-timeout 240
docker compose restart
docker compose up -d --wait --wait-timeout 240
```

Also test missing secrets on a fresh isolated project, persisted config/realm
after recreation, and backup restoration. Inspect private port bindings. Never
introduce a second queue consumer for testing. Full-stack Docker Engine behavior,
backup/restore drills, and real provider/Langfuse flows remain explicit validation
gates; see `DEVELOPMENT.md` for completed checks.
