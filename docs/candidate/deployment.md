# Isolated LiteLLM candidate deployment

**Observed October 29, 2026; issue #2 configuration/startup tranche.** Native
community ordinary-user login and empty personal Usage work on this pin. Shared
A1–A6, provider inference, Langfuse acceptance and production adoption remain
pending. [Setup decisions](decisions.md), [contract](../specs/litellm-poc.md).

## Pins and source verification

| Component | Verified selection |
|---|---|
| LiteLLM | Official `ghcr.io/berriai/litellm:v1.106.6`, Linux amd64 manifest `sha256:c09a77d998058dd78835a45a985eae747d257f2b183db06852fba536f3d1113c` |
| Release/source | `v1.106.6`, published `2026-10-28T23:03:09Z`; commit `61c6ab78393ef45683dd7d963d2a315bd845e20b`; image OCI revision and installed Python package `1.106.6` match |
| Edition | No `LITELLM_LICENSE`; native A/B login tokens report `premium_user=false`, role `internal_user` |
| PostgreSQL | Official `docker.io/library/postgres:17.11`, Linux amd64 manifest `sha256:0b81cec82228160abfa753aeaad0609b709eb26eeb950f2e404ad2326e1cc370` |
| Schema | Installed `litellm/proxy/schema.prisma` SHA256 `1ed6fbff070ed7cdf2fa86f667d7b6eedd6a0be2d7036250a54cfe360de183db`, equal to pinned source file |
| Migration state | Native automatic startup migrations: 213 finished, latest `20261009000000_add_credential_display_name` |
| Price map | Bundled map SHA256 `66970be01c88f94618f9f69c1a1d29e400474f2d7b89973de7e373c110f455c2`; `LITELLM_LOCAL_MODEL_COST_MAP=True` prevents floating remote-map fetch |
| Actual client | OpenCode `2.2.1`, installed `/home/xzx/.opencode/bin/opencode`; actual-client cases belong to #7 |

Checked the official release API, tag-to-commit API, registry manifests, local
image labels/package/schema, and pinned source. `main-v1.106.6-stable` does not
exist; the official release's `v1.106.6` does. These are registry/source pin checks,
not a claim that cosign signature verification was performed.

Primary references (checked October 29):

- `https://github.com/BerriAI/litellm/releases/tag/v1.106.6`
- `https://github.com/BerriAI/litellm/tree/61c6ab78393ef45683dd7d963d2a315bd845e20b`
- `https://github.com/docker-library/postgres` and the official `postgres:17.11` registry manifest
- `https://docs.litellm.ai/docs/proxy/self_serve`
- `https://docs.litellm.ai/docs/proxy/virtual_keys`
- `https://docs.litellm.ai/docs/proxy/redis_requirements`
- `https://docs.litellm.ai/docs/proxy/ui_logs`
- `https://docs.litellm.ai/docs/proxy/config_settings`
- `https://docs.litellm.ai/docs/proxy/security_encryption_faq`

Pinned source evidence: `litellm/proxy/auth/login_utils.py:395–459` authenticates
DB users without an enterprise gate; `proxy_server.py:17716` handles `/v2/login`,
`:17919` issues onboarding tokens, `:18121` claims invitations, `:18417` creates
invitations. `management_endpoints/internal_user_endpoints.py:538` documents the
password rejection on `/user/new`. Runtime browser evidence below confirms the
selected ordinary-user path rather than relying on generic live documentation.

## Ownership, ingress and storage

`deploy/candidate/compose.yaml` owns only LiteLLM and a new PostgreSQL container.
Project `proxylens-candidate`; volume `proxylens-candidate_candidate_db`; private
internal database network. Database has no published port. LiteLLM publishes
`127.0.0.1:14000` only. The source-controlled `compose.yaml` and old runtime are
separate. PostgreSQL holds native users/password hashes, hashed virtual keys,
usage and native configuration. Retain it together with master/salt secrets;
#6 owns backup/restore and migration policy.

The [candidate recovery runbook](recovery.md) records actual retention, state/secret
ownership and a populated account/key/policy restore on this pin. Retained request
history and production acceptance remain pending; use its standalone offline
restore Compose rather than the existing-runtime `scripts/recovery.py` package.

Reuse the authorized CPA test service on external network
`plcodex-live-645179fc_provider`, DNS `cliproxyapi:8317`. Inference base is
`http://cliproxyapi:8317/v1`. Host health is `http://127.0.0.1:35635/healthz`.
The candidate copies the existing **inference** service credential into its
private secret directory. No CPA management credential enters the candidate.
It shares provider capacity/state with the authorized test service; it does not
claim provider isolation. Existing CPAMP stays the sole queue consumer; neither
CPAMP nor its queue is used by the candidate. No queue access was performed.

## Reproduce

Run from repository root. Requires Python 3, Podman or Docker, and Compose v2+
compatible CLI. Existing host uses Podman 5.7.0 and Compose 5.6.1.

```sh
export PRIVATE=/data/tmp/opencode/proxylens-litellm-20261029/private
# For a NEW deployment choose a new, nonexistent PRIVATE directory.
python3 scripts/candidate.py init \
  --private-dir "$PRIVATE" \
  --cpa-key-file /path/to/authorized/cpa-inference-key \
  --cpa-network plcodex-live-645179fc_provider \
  --cpa-base http://cliproxyapi:8317/v1
```

`init` refuses existing state. Directories are 0700, credentials/fixture/env 0600,
outside the repository. It generates distinct DB, master, salt and admin-password
secrets; no values are printed. Preserve master/salt on restart. Compose secrets
are mounted read-only and `secret_env.py` loads only named files before execing
upstream's entrypoint. Secrets are not interpolated into Compose environment
values or shell source. The native process still needs them in its environment.

Podman setup for this host (dedicated socket, start once in another terminal):

```sh
podman system service --time=0 \
  unix:/data/tmp/opencode/proxylens-litellm-20261029/podman.sock
```

```sh
export DOCKER_HOST=unix:///data/tmp/opencode/proxylens-litellm-20261029/podman.sock
export COMPOSE=/data/tmp/opencode/docker-compose-v5.6.1
"$COMPOSE" --env-file "$PRIVATE/candidate.env" \
  -f deploy/candidate/compose.yaml up -d --wait --wait-timeout 180
python3 scripts/candidate.py fixture --private-dir "$PRIVATE"
```

Docker users can substitute `docker compose` and omit `DOCKER_HOST`. The fixture
command targets loopback only and must run once against a fresh candidate DB.
Partial failure preserves `fixture.partial.json` for private diagnosis; do not
blindly rerun and mint more keys. Existing `fixture.json` is deliberately reused.

The helper performs native admin login first (creates the administrator row needed
by invitation foreign keys), then `/user/new` without password or auto-key,
`/invitation/new`, `/onboarding/get_token`, `/onboarding/claim_token`, `/v2/login`,
and `/key/generate` with explicit `user_id`. It does not implement identity/CRUD.

Interactive smoke: open `http://127.0.0.1:14000/ui/login`, use A then B's private
email/password, select **Usage**, confirm **Internal User** and **Your Usage**.
Do not copy tokens/screenshots with credentials into repository evidence.

## Selected native controls and pricing

- A=`candidate-user-a`, B=`candidate-user-b`, role `internal_user`; A owns keys
  A/A2, B owns B. Admin `candidate-admin` is setup-only. No admin-viewer workaround.
- Allowed alias `cpa-gpt-5.6-luna`, backend `openai/gpt-5.6-luna`, mode `responses`.
  CPA `/v1/models` advertised `gpt-5.6-luna` on October 29. Health and model discovery
  do not prove inference; #7 owns actual OpenCode/protocol checks.
- Each user and fixture key: native **10 requests/minute, 20,000 tokens/minute**.
  New personal keys inherit the same defaults. The user-level limit aggregates
  their keys. One worker/replica, native in-memory counters; restart loses volatile
  counters. No Redis is required for this selected single-worker POC. Do not scale
  it without coordination configuration. Native windows/propagation and one
  denial are measured in A4, not certified here.
- No monetary budget, key-expiry override, response cache or paid policy feature.
  UI session budget/expiry, limit algorithms and DB write batching retain native
  defaults. No strict never-overspend or lossless accounting claim. Zero retries
  configured in LiteLLM/router; CPA's existing execution policy is separate.
- Explicit standard API-equivalent USD per million tokens: input **0.20**, cache
  read **0.02**, cache write **0.25**, output **1.20**. Above 272k input: **0.40**,
  **0.04**, **0.50**, **1.80**. Config uses per-token units. Verified against
  `https://developers.openai.com/api/docs/models/gpt-5.6-luna` and the pinned
  bundled map. `/model/info` returns these configured numeric values.
- Prices estimate API-equivalent cost, not subscription expenditure or a bill.
  Alternate service tiers, tool fees and extended cache retention are not selected
  fixture scenarios; upstream's bundled pricing remains the fallback. Missing
  provider usage cannot become a credible zero. #7 reconciles the sample's native
  retained usage/cost rather than implementing new accounting.

## Current logging settings and #8 target

**Current checked-in setup, not the approved tracing target:**
`turn_off_message_logging=true`, `global_disable_no_log_param=true`,
`store_prompts_in_spend_logs=false`,
`disable_spend_logs=false`, `disable_error_logs=true`, no debug/verbose mode,
ERROR log level. Detailed error-table persistence is disabled because exceptions
may include content; this limits current diagnostics. These settings are unchanged
by the October 29 objective revision. #8 will configure native Langfuse content
capture and useful errors under the [approved debugging objective](../specs/litellm-poc.md#native-debugging-traces).
Admin UI overrides can change native logging settings; #8 must record the effective
configuration, including any overrides, rather than assume the file alone proves it.
Langfuse content capture does not itself require spend-log prompt storage or
verbose process logging.
Onboarding-token query paths and health paths are excluded from access logs using
the verified `LITELLM_DISABLE_ACCESS_LOG_PATHS` setting. Do not use the nonexistent
`DISABLE_ACCESS_LOGS` setting. No credential values found in current candidate
container logs after smoke. This is not A5 privacy evidence for inference.

Local synthetic fixture disables `password_policy_check_breached_passwords` to
avoid HIBP hash-prefix egress; other native password policy checks remain enabled.
Backend telemetry and remote price-map fetch are disabled. The browser home page
may still load upstream news; this is not an offline deployment.

`general_settings.user_header_mappings` is currently unset. The installed 1.106.6
`litellm_logging.py` consumes `global_disable_no_log_param`; setting it explicitly
prevents caller `no-log` from opting out of configured logging. This does not
establish trusted attribution, credential masking or debugging-content coverage
on every callback outcome.

No callback is enabled by #2. `secret_env.py` supports
`LANGFUSE_PUBLIC_KEY_FILE` / `LANGFUSE_SECRET_KEY_FILE`; #8 can mount Compose secrets,
set their file paths plus native destination, attach the selected Langfuse network
and configure **one** native integration in the candidate config/overlay. #8 owns
the separate test project/destination, native content settings, trusted
identity/session mapping and targeted credential masking. #7 verifies A5 using
shared synthetic content, including source code and visible tool interactions,
plus error and outage cases. #6 records native project access/roles and content
retention/deletion; `userId` is an analysis dimension, not reader authorization.

Start with native configuration. Only a demonstrated, narrowly selected
mapping/credential gap justifies a minimal read-only-mounted hook and focused
regression tests. No replacement exporter/outbox or blanket content-stripping
adapter is planned. Credential masking does not promise removal of every embedded
secret; traces cannot show local tool execution or files never sent to the gateway.

Earlier pinned-source research raised success-only hook coverage and caller-selected
callback destinations as verification concerns. Reassess those concerns against the
selected native configuration; they do not mandate a callback-local adapter.
The metadata-only target and blanket filtering proposal in that research are
superseded by the [owner decision](decisions.md#owner-approved-tracing-objective-october-29-2026).
Research handoff (historical input):
`/data/tmp/opencode/proxylens-litellm-20261029/telemetry-research.md`.
Native delivery, content, attribution and credential checks remain unperformed;
the existing smoke does not prove them. #7 records missing/truncated native fields
and other coverage limits for owner review. Native project configuration in #6
does not introduce a separate UI/access implementation project.

## Stop, restart and rollback

```sh
"$COMPOSE" --env-file "$PRIVATE/candidate.env" \
  -f deploy/candidate/compose.yaml stop
# Start again, retaining the same private directory, pins and volume:
"$COMPOSE" --env-file "$PRIVATE/candidate.env" \
  -f deploy/candidate/compose.yaml up -d --wait --wait-timeout 180
# Remove candidate containers/network but RETAIN state:
"$COMPOSE" --env-file "$PRIVATE/candidate.env" \
  -f deploy/candidate/compose.yaml down
```

Do not use `down -v` for state-preserving rollback. The external CPA network and
legacy deployment remain running. To abandon the experiment, stop the candidate
and use the existing ingress; no cutover occurred. Binary downgrade against a
migrated DB is not an approved rollback; #6 must prove matching-state restore.

## Evidence and handoff

Observed on the configured pin:

- Compose startup passed; PostgreSQL and LiteLLM healthy; database connection ready.
  Initial Podman healthcheck failed because argv lost Python `-c` quoting; fixed
  with quoted `CMD-SHELL`, focused regression added, startup rerun passed.
- Native A/B JSON and browser login succeeded with `premium_user=false` and
  `internal_user`; both opened `/ui/usage/` with **Your Usage**, empty counters,
  native model/key/time-range controls. No paid/edition blocker observed here.
- Three personal keys created with explicit intended owner and configured limits.
  Admin, CPA service and personal credentials are distinct. Native `/model/info`
  confirmed prices; candidate-to-CPA health returned 200.
- Reproducible `init` → Compose → `fixture` sequence passed on a second fresh
  project/DB (`proxylens-candidate-setup-check`, port 14001). That project's
  containers/network were removed with `down`; its volume/secrets were retained.
- Main candidate was recreated after config fixes with same persistent DB and
  secrets. #7 still owns completed-request persistence evidence.
- Focused bootstrap regression tests and Ruff passed. No provider inference,
  cross-user denial, usage reconciliation, limit exercise or Langfuse acceptance
  performed by #2. Empty Usage is startup evidence, not A1–A6 completion.

Live handoff: `http://127.0.0.1:14000`; Compose project `proxylens-candidate`;
private `/data/tmp/opencode/proxylens-litellm-20261029/private/candidate.env`,
`fixture.json`, `secrets/`. Leave these resources for #8/#7/#6. Private fixture
contains `base_url`, `model`, `users.A/B` with login/password/session and `keys`
maps (`A`, `A2`, `B`). Refresh sessions via native login if expired. Production
readiness, retention and adoption remain gated by #6/#1 and the shared checks.
