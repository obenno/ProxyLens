# Candidate native Langfuse tracing

**October 29, 2026 — #8 configuration tranche. A5 remains pending #7.**
Uses the [content-rich contract](../specs/litellm-poc.md#native-debugging-traces).
Runtime activation/readback status is recorded below; neither configuration nor
synthetic callback tests establish shared acceptance or production adoption.

## Selected native path and demonstrated gap

LiteLLM **1.106.6**, image digest
`sha256:c09a77d998058dd78835a45a985eae747d257f2b183db06852fba536f3d1113c`,
installed Langfuse Python **4.15.2**, OpenTelemetry SDK/HTTP exporter **1.45.1**,
HTTPX **0.28.1**. Destination: existing authorized local Langfuse **4.69.0**;
its state and old project are preserved. [Deployment pin record](deployment.md).

The native `langfuse` logger supports SDK 4 and server >=3.63.0. It constructs
Langfuse observations and uses LiteLLM's native OTLP queue/batching/transporter.
The SDK REST client provides project checks/prompt management. We use **one**
`CustomLogger` instance, `native_langfuse.native_langfuse`, delegating to that
unchanged `LangFuseLogger.log_event_on_langfuse`. No parallel `langfuse`,
`langfuse_otel`, generic OTel exporter, outbox or inference retry code is registered.

Native configuration was evaluated first. Installed-source and serialized native
OTLP probes demonstrated:

1. `user_api_key_user_id` is retained as metadata but native `user.id` defaults to
   customer/end-user identity. Caller `trace_user_id` and `langfuse_trace_user_id`
   override it; session controls are similarly caller-controlled.
2. Native auth-header exclusion worked in the synthetic probe; a synthetic
   credential in error text survived in observation output/status message.

**Important probe correction:** request preparation/dynamic initialization alone
accept caller Langfuse host/public/secret parameters, but the deployed auth layer
rejects them first (401). `allow_client_side_credentials` is unset and no model
opts in. Installed `proxy/auth/auth_utils.py:299–371,451–495` covers both metadata
slots. The preparation-only probe bypassed that gate: it does **not** demonstrate
a deployed destination-control vulnerability. Retain native credential rejection;
the wrapper also uses a fixed server-side logger rather than dynamic selection.

The coordinator was given the exact gap and minimal public seam before proceeding
under the selected targeted-mapping/credential requirement. OTel v2 was considered:
its `TraceControls` also deliberately accepts caller user/session controls.
Changing integration alone does not resolve these demonstrated requirements.
Native `langfuse` has the smaller callback-local boundary for this deployment.

## Narrow hook contract

`deploy/candidate/native_langfuse.py` receives native asynchronous terminal
success/failure events, including native completed-stream assembly. It builds
callback-local copies, then delegates payload construction and delivery to the
native logger. It does not modify provider input/output or native Usage facts.

- Owner source: `standard_logging_object.metadata.user_api_key_user_id`, stamped
  by pinned proxy authentication. The proxy strips caller `user_api_key_*` fields
  from both metadata slots and reconstructs authenticated metadata for proxy-only
  failures. Missing trusted owner stays **unattributed**; caller `user`, customer
  labels and raw metadata are never fallback owners.
- `userId`: `proxylens-candidate/<percent-encoded-key-owner>`. A/A2 share the owner;
  B differs. This identifies key ownership, not a verified interactive human.
- `sessionId`: `<userId>/request/<random-id>`, or deployment-scoped unattributed
  fallback. `session_basis=request_fallback` labels it. No verified conversation
  mapping exists yet; client sessions are deliberately not presented as trusted
  conversations. Trace IDs are fresh server-generated values; caller trace IDs,
  parents, public flags and destination controls cannot steer them.
- One fixed native logger reads server-side `LANGFUSE_HOST`, public/secret files,
  with credential fallback disabled. No caller-selected `LangFuseHandler` path.
- Prompts/source, responses, visible tools, image references and useful errors
  remain. Credential-bearing structured keys and text assignments (authorization,
  API keys, access/refresh/OAuth/ID tokens, provider/management/client keys/secrets,
  passwords, cookies), Bearer/Basic credentials, and exact configured gateway/CPA/
  Langfuse secrets are masked. JSON string delimiters are preserved. Auth/request
  headers and arbitrary caller diagnostic metadata are not copied into telemetry.
- This is targeted masking, not a guarantee to detect arbitrary embedded secrets,
  encodings or unknown credential formats. Inputs are copied recursively; no new
  payload truncation, storage, queue or native cost normalizer is introduced.
- Callback construction/work runs off the event loop. Errors produce a fixed
  process-log message; inference is never invoked by telemetry. Native async
  delivery/flush still governs actual loss and restart behavior.

## Separate native project and access

Created through native signup/login and authenticated organization/project/key
operations, without shared-container reconfiguration or direct database writes:

| Field | Selected value |
|---|---|
| Organization | `ProxyLens Candidate 2026-10-29`, `cmvtf4q0c0001mu251ogkp2f9` |
| Project | `LiteLLM native synthetic tracing`, `cmvtf4q110005mu25rx45vwbn` |
| Host browser/API | `http://127.0.0.1:38755` |
| Container origin | `http://langfuse-web:3000` on `pllf469-7c854f95_default` |
| Operator | Separate candidate operator; native org/project inherited `OWNER`; instance `admin=false` |
| Edition | Native session reports `oss` |
| Project credentials | Native default legacy full-access project key; private server-side only |
| Retention | Native `retentionDays=null`; no automatic expiry selected |

The new organization has only the candidate operator; A/B have no Langfuse
membership or keys. Operator and holders of this project key can read all its
traces. `userId` filters do **not** grant personal isolation. OSS inherits org
roles; finer project-role overrides are edition-dependent. #6 owns any future
reader grants, content-retention/deletion/recovery decision. No production
retention approval follows from this synthetic-only project. Native project
deletion is available to its owner; do not delete the old project's fixtures.

Private login/creation state:
`/data/tmp/opencode/proxylens-litellm-20261029/issue8-private/langfuse-project.json`.
Raw synthetic probes/readback are under that 0700 directory, files 0600.
Staged runtime credentials/environment:
`/data/tmp/opencode/proxylens-litellm-20261029/private/langfuse/`.
No key values, cookie/session dumps or private content belong in Git.

## Reproduce configuration

Create a separate native organization/project as an authorized operator, then
create a project key in **Project Settings → API Keys**. Save the two key values
to private files. Existing project-scoped credentials cannot create another
project. This local service permitted signup; a new non-admin candidate operator
created its own organization/project. The private one-shot setup script records
the actual native API calls; it is not a replacement identity service.

```sh
export PRIVATE=/data/tmp/opencode/proxylens-litellm-20261029/private
python3 scripts/candidate.py langfuse \
  --private-dir "$PRIVATE" \
  --public-key-file /path/to/new-project-public-key \
  --secret-key-file /path/to/new-project-secret-key \
  --base-url http://127.0.0.1:38755 \
  --container-base http://langfuse-web:3000 \
  --network pllf469-7c854f95_default \
  --project-id cmvtf4q110005mu25rx45vwbn
```

The public setup command authenticates `GET /api/public/projects`, requires
exactly the expected project, then creates 0700/0600 state. It refuses existing
state rather than rotating or overwriting keys. It does not activate tracing.

Use both Compose files/env files after coordinating #7 and committing the mounted
source. Recreate **only candidate LiteLLM**, retaining PostgreSQL, existing keys
and fixture. The active mounts now come from issue8; coordinate any mounted-source
change or recreation with #7, which owns runtime coordination during acceptance.

```sh
export DOCKER_HOST=unix:///data/tmp/opencode/proxylens-litellm-20261029/podman.sock
export COMPOSE=/data/tmp/opencode/docker-compose-v5.6.1
"$COMPOSE" --env-file "$PRIVATE/candidate.env" \
  --env-file "$PRIVATE/langfuse/langfuse.env" \
  -f deploy/candidate/compose.yaml -f deploy/candidate/langfuse.compose.yaml config --quiet
"$COMPOSE" --env-file "$PRIVATE/candidate.env" \
  --env-file "$PRIVATE/langfuse/langfuse.env" \
  -f deploy/candidate/compose.yaml -f deploy/candidate/langfuse.compose.yaml \
  up -d --no-deps --force-recreate --wait --wait-timeout 240 litellm
```

Activated settings: `turn_off_message_logging=false`,
`global_disable_no_log_param=true`, single callback above;
`store_prompts_in_spend_logs=false`, `disable_spend_logs=false`,
`disable_error_logs=true`, ERROR process log level, no verbose/debug mode,
`LANGFUSE_DEBUG=False`, environment `candidate`. No user-header mapping.
Content is enabled for the selected trace path, not duplicated into native spend
logs. Native error-table persistence remains disabled; callback error visibility
is separate. Administrator DB/UI overrides must be checked at deployment.

## Validation and native limitations

**Performed without provider inference:**

- Installed native proxy preparation retains trusted key owner while leaving
  forged trace controls intact: confirms the attribution gap. Destination controls
  were tested separately through deployed auth and rejected before preparation.
- Native logger → serialized OTLP capture, in pinned image with `--network none`.
  Six focused project-hook checks pass: A/A2/B owner/fallback sessions; forged
  controls/destination; unchanged inputs; credential canaries in content/tool/
  model parameters/errors; JSON preservation; unattributed early callback;
  native Responses dispatch and completed-stream tool/image content.
- Native logger → real separate-project readback produced one synthetic
  `GENERATION`, transmitted source, output, function-call arguments, tool result,
  owner/session, original one-second timing and supplied estimated cost.
- Initial *direct* `ResponsesAPIResponse` probe bypassed native dispatcher usage
  conversion and showed 0/0 input/output despite total140. Running the **native
  dispatcher** correctly produces input80/cache20/output40/total140 for inclusive
  input100/cache20/output40. No custom normalization added. Native SDK callback
  does not emit a separate reasoning bucket; output40 includes reasoning10.
- Eight focused setup tests pass; they cover private staging, project mismatch,
  malformed response and no credential rotation. CI runs the six native seam
  checks in the exact deployment image separately from old-runtime tests.

### Repeat the focused checks

The six serializer/dispatch checks require the pinned LiteLLM runtime dependencies;
they are intentionally separate from the repository's ordinary pytest discovery.
From the repository root, use Docker (as in CI) or substitute `podman`:

```sh
docker run --rm --network none \
  -v "$PWD:/work:ro" --workdir /work --entrypoint python \
  ghcr.io/berriai/litellm:v1.106.6@sha256:c09a77d998058dd78835a45a985eae747d257f2b183db06852fba536f3d1113c \
  -m unittest discover -s tests -p candidate_native_contract.py
python -m pytest tests/test_candidate_bootstrap.py -q
```

The container uses only a synthetic loopback OTLP receiver, without live secrets
or provider access. `.github/workflows/ci.yml` job `candidate-native-tracing`
executes the first command; the ordinary checks job includes the bootstrap tests.

### Delivery and content limits

Native limits from installed source: in-memory queue100,000, batch512,
flush interval1s, sampling1, HTTP timeout20s, three delivery retries after initial
attempt by default. Connect/read failures and HTTP408/429/5xx are retried by native
delivery. HTTP413 splits batches and may truncate largest input/output/metadata
fields, then drop an irreducible span. Queue overflow, crash/restart and rejected
exports can lose observations; no durable/exactly-once promise. Native shutdown
flush is bounded. No sink-delivery retry executes inference.

Image URLs/data remain serialized content; no local-file/media-upload or complete
local-agent trace is implied. Local tool execution is absent; results appear only
when transmitted. Completed streams are native assembled terminal observations,
not per-token spans. Error/`response.failed` dispatch is native; client cancellation
can bypass normal failure callbacks and partial content may be absent. No custom
interruption recorder is selected. Missing usage/pricing is not credible zero;
native coercions and absent reasoning decomposition must be recorded in A5.

**Runtime status:** activated from commit `d52f4b1`, source mounts relocated from
issue2 to issue8 using the command above. Only candidate LiteLLM was recreated;
candidate PostgreSQL and shared CPA/Langfuse web/worker IDs/start times unchanged.
Health passed; native `/get/config/callbacks` reports only this single configured
success/failure callback. `LiteLLM_Config` contains only
`auto_router_tuning_baseline_v3`, no logging override. Mounted config/loader/hook
match the committed source. Startup process logs contain no error or configured
credential value. Pin/dependency versions unchanged.

Two deployed denial smokes required no provider: caller destination metadata was
rejected401 before authenticated attribution (trace explicitly unattributed);
valid A key with nonexistent model and forged user/session metadata was rejected403
and produced an ERROR observation with trusted A owner/request-fallback session.
The latter trace is `866bc30c480544e786de7dfdfb6ad85a`; forged controls and personal
key absent from readback. Project includes these denied requests plus the direct
synthetic sample; it is not an empty counting fixture. This is auth/callback setup
evidence, not real-provider error or A5 outage evidence.

#7 owns shared real-provider A2/A5 content/error/forgery/readback/outage
evidence. Sink failure must not replay inference; native client retries remain
accepted under [Retry boundaries](../specs/litellm-poc.md#retry-boundaries).
Do not close #8 before A5 evidence is linked.

### Exact activation evidence and shared fixture

Paths below are relative to
`/data/tmp/opencode/proxylens-litellm-20261029/`, outside Git:

| Artifact | Purpose |
|---|---|
| `issue8-gap-handoff.md` | Coordinator readiness, gap correction and shared-case handoff |
| `private/fixture.json` | Existing A/A2/B keys, owners and candidate endpoint; reuse without rotation |
| `private/candidate.env` | Base Compose environment |
| `private/langfuse/langfuse.env`, `public_key`, `secret_key` | Telemetry overlay environment and separate-project credentials |
| `issue8-private/langfuse-project.json` | Native operator login/project creation and access state |
| `issue8-private/{native_probe.py,payloads.json,result.json}` | Original serialized native attribution/error-credential gap |
| `issue8-private/{native_readback.py,native-live-readback.json}` | Direct synthetic native delivery/readback |
| `issue8-private/{before-recreate.json,startup.log,effective-callbacks.json}` | Activation snapshot, startup log and native callback configuration |
| `issue8-private/gate-smoke-readback.json` | Both actual denied-request observations, including trusted A trace above |
| `issue8-private/activation-summary.json` | Verified saved-readback summary and artifact references |

The first `gate-smoke-summary.json` captured an earlier401 observation while the
subsequent403 was still ingesting; it is preliminary, not the final ownership
result. The final readback contains both trace IDs. `deployed_gate_smoke.py` is a
historical one-shot probe, not a fresh-run counting harness; #7 uses its shared
runbook and exact request correlation. Private artifact directories/files are
0700/0600. No additional configuration decision is blocking #7; shared A5 and
production access/retention decisions remain with #7/#6 respectively.

## Sources checked October 29, 2026

- `https://docs.litellm.ai/docs/observability/langfuse_integration`
- `https://docs.litellm.ai/docs/proxy/call_hooks`
- `https://langfuse.com/docs/administration/rbac`
- `https://langfuse.com/self-hosting/administration/headless-initialization`
- Installed/pinned LiteLLM source at commit
  `61c6ab78393ef45683dd7d963d2a315bd845e20b`:
  `integrations/langfuse/{langfuse.py,langfuse_handler.py,langfuse_sdk.py}`,
  `litellm_core_utils/{litellm_logging.py,initialize_dynamic_callback_params.py}`,
  `proxy/{litellm_pre_call_utils.py,utils.py}`,
  `integrations/otel/model/trace_controls.py`, `responses/streaming_iterator.py`.
  Critical locations: logger749–752/800–810/820–843; dynamic params95–143/177–212;
  pre-call2156–2178/2358–2382; logging2532–2546/3507–3515/4019–4025;
  proxy-only errors3764–3812. Exact installed copies retained privately.

For changes, rerun `tests/candidate_native_contract.py` in the new pin, inspect
trusted metadata provenance before accepting it, and reuse shared A5. Preserve
native retry/delivery semantics and the selected content objective.
