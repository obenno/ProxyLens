# Responses gateway

> **Current implementation / original #7.** Revised #7 validates LiteLLM → CPA;
> see the [POC contract](specs/litellm-poc.md). The behavior below describes the
> custom gateway and is not evidence that the candidate preserves it.

The `gateway` service accepts `POST /v1/responses`. Authenticate with an issued
ProxyLens client key in `Authorization: Bearer …`. The `api` service exposes
Keycloak-authenticated `/api/applications`, key lifecycle and policy routes.
`Database.migrate()` runs under the shared migration lock before service startup.

## Operator routing contract

Populate `deploy/gateway/routes.json` from the **verified deployed CPA routing
configuration**, then restart the gateway. The default `{}` denies every model.
The file is mounted read-only; it contains routing metadata, never credentials.
Synthetic shape:

```json
{
  "example-alias": {
    "model": "example-resolved-model",
    "provider": "codex",
    "verified": false
  }
}
```

Set `verified: true` only after establishing that **every possible route/failover
for this exact alias** uses that provider and model on the pinned CPA deployment.
A `models` listing alone is not provider-routing evidence. No inferred provider
names, wildcard matching, unverified entries, duplicate JSON keys or guessed
fallbacks. If routing can select another model/provider, leave the alias disabled.
Keep CPA configuration and this registry synchronized; restart after changes.
This attestation is not the separate live request-correlation proof gate.

Both the requested alias **and** resolved target must occur in the effective
model policy; the attested provider must occur in its provider policy. Explicit
group/application allowlists intersect. Missing effective lists deny. The request
body still carries the original alias: CPA owns model translation.

## Authorization and secrets

- Keys and policies are read from PostgreSQL for every request; no gateway cache.
  Committed revocation affects the next request across gateway processes. Already
  authorized in-flight traffic continues under its authorization snapshot.
- Group existence is checked live through the existing Keycloak `GroupAuthority`.
  Only matching-issuer, flat `ACTIVE` evidence permits use. Authoritative absence
  invokes transactional resource reconciliation/orphan marking. Nested groups and
  outages deny without falsely marking deletion. The platform-admin reconciliation
  route remains available; periodic fleet reconciliation is an operations task.
- `ResourceAccess` uses signed `Principal.group_ids`, `group-member`, capability
  and scope semantics. It does not use the earlier test-placeholder `groups/member`.
- Gateway receives only the CPA **client** credential and the existing read-only
  Keycloak authority credential. The latter has `view-users`/`query-groups`, the
  pinned realm's group-read grants; no realm/user-management write privileges.
  CPA Management and CPAMP admin credentials are not mounted in the gateway.
- Outbound headers are freshly constructed: service authorization, JSON content
  type, identity encoding, generated request ID. Client identity/session/credential
  headers and arbitrary inbound headers never replace server-resolved ownership.

## Bounded forwarding

Defaults: 4 MiB JSON body, 120-second total request deadline, 30-second upstream
I/O inactivity timeout. Configure `PROXYLENS_MAX_BODY_BYTES`,
`PROXYLENS_TOTAL_TIMEOUT`, `PROXYLENS_IDLE_TIMEOUT`. Policy body/time ceilings can
only tighten these limits. The total deadline includes upload, authorization,
lineage commits, pool/connect/header wait, stream read and downstream backpressure.
Completion metadata gets a separate maximum three-second cleanup attempt after
closing upstream. Request bodies are bounded-buffered; successful response bytes
are forwarded without parsing, reserialization or full-response buffering.

Only UTF-8 JSON objects with a string model and optional boolean `stream` are
accepted. Duplicate object keys, non-JSON constants and compressed ingress are
rejected. Chunked bodies obey the same actual-byte limit as declared-length bodies.
Tools, multimodal input, metadata and other permitted protocol fields pass through
unchanged. SSE errors remain protocol bytes; a completed HTTP stream does **not**
prove successful inference.

Rate caps use the existing atomic PostgreSQL key/application 60-second windows,
shared across instances. A reservation can remain consumed if later authorization
lineage fails; no automatic refund or retry. There are **zero automatic model POST
retries**, including pre-byte connection failures and timeouts. This is the explicit
safe policy for ambiguous provider admission: ProxyLens never replays a model
request merely because no response bytes were observed. CPA's internal
retry/failover policy remains its own operator-controlled provider boundary.

Disconnects cancel the upstream operation, including during response-header wait.
Timeouts/transport errors after headers close the partial connection without a
fabricated SSE terminal event. A real-provider cancellation claim still requires
the coordinator's live CPA/Codex test.

## Errors and correlation

Errors use `{"error":"fixed_code"}`: invalid key 401; policy/routing denial 403;
invalid JSON 400; size 413; encoding/media type 415; rate 429; unavailable
authorization/storage 503; upstream timeout 504; connection/protocol failure 502;
unknown post-dispatch failure 500. Upstream HTTP 4xx/5xx status is retained with a
redacted `upstream_error` body; redirects are not followed and become 502. Raw
upstream error bodies and privileged headers never reach the error envelope.

Ingress lineage and `gateway_lifecycle` are committed together **before** the
single upstream POST. Failed durable ingress means zero provider requests. On
headers, the pinned parser binds actual `X-CPA-TRACE-ID` via `LineageRepository`.
Responses expose generated `X-Request-ID` and, when valid, UUID-only
`X-CPA-Request-ID`; the composite header/auth index is never exposed or persisted.
Malformed/multiple trace headers remain missing. Native collisions retain all
bindings, invalidating scoped correlation rather than overwriting ownership.

Header-binding DB failure closes upstream and returns 503 before downstream
headers. Completion DB failure preserves pending/unknown state and increments the
gateway metadata failure counter; readiness reports `gateway_metadata: degraded`.
Logs contain only a fixed event name and generated request UUID. No provider
replay repairs telemetry. A process crash also leaves pending intent, which is
neither proof of dispatch nor proof of non-dispatch.

## Exporter interface (migration 007)

`gateway_observations` is the internal read contract: it joins immutable
`lineage_ingress` owner, subject, generated session/trace/generation IDs with:

| Field | Meaning |
| --- | --- |
| `requested_model` | Exact allowed request alias |
| `routing_model`, `routing_provider` | Operator-attested targets, **not observed resolution** |
| `group_policy_version`, `application_policy_version` | Authorization decision versions |
| `dispatch_intent_at` | Durable intent before network dispatch; not acceptance evidence |
| `headers_at`, `first_byte_at`, `completed_at` | UTC timestamps, null if unavailable |
| `http_status` | Upstream HTTP status when received, not SSE semantic status |
| `duration_ms`, `response_bytes` | Elapsed time and successful downstream byte sends |
| `outcome` | `pending`, `completed`, `upstream_error`, `timeout`, `cancelled`, `transport_error`, `storage_error`, `internal_error` |

Wait for `completed_at` before final export, or apply an explicitly bounded
stale-pending/unknown policy in the exporter. Completion is written once. Read
native bindings/collisions at export time; never cache presumed scoped ownership.
Machine requests leave `subject` null and use generated ingress UUID as session;
do not attribute them to the key creator or caller headers. Any machine `userId`
convention belongs to the exporter and must remain explicit.

No raw input/output/tools/images/metadata/error bodies, authorization headers or
keys are stored. No token/cost fields are invented. Tenant usage remains subject
to existing live proof gates. The exporter must separately finalize its generation
exactly once; this view is metadata input, not an outbox or usage ledger.

## Validation

`tests/test_application_wiring.py` verifies actual signed JWTs through production
resource routes and PostgreSQL. `tests/test_gateway.py` runs real local TCP
gateway/upstream servers: first-byte barrier, disconnect cleanup, timeout, error,
payload/credential preservation, revocation, rate contention, alias restrictions,
size bounds and database failpoints. Synthetic fixtures are not live-provider
compatibility or correlation proof.
