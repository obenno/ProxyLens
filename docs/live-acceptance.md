# Phase 1 live acceptance harness

> **Historical/current-runtime evidence.** These cases exercise the original
> #1–#10 architecture. Candidate A1–A6 start unperformed under the
> [integration plan](specs/litellm-poc.md), which maps the broader handoff scenarios
> to retained/deferred scope. Old successful cases do not pass candidate checks.

`scripts/live-acceptance.py` is a deliberately private, one-shot acceptance
harness for the already authorized local CPA/CPAMP runtime. It is not a proof
gate enabler and never calls a CPA usage-queue route. It reads the actual pinned
CPA configuration/credential registry through the owner-only setup helper,
attests the selected model route, creates two synthetic ProxyLens applications
through signed Keycloak bearer tokens, and sends only tiny synthetic Responses
requests through the real ProxyLens gateway.

## Run contract

The coordinator prepares the owner-only manifest and route attestation, starts
the API/gateway/worker processes, refreshes synthetic Keycloak tokens, and then
invokes one case at a time:

```sh
PYTHONPATH=src .venv/bin/python scripts/live-acceptance.py \
  --manifest /data/tmp/opencode/proxylens-phase1/live-acceptance-20261027/manifest.json \
  --directory /data/tmp/opencode/proxylens-phase1/live-acceptance-20261027/cases \
  dispatch --case nonstream
```

The harness reserves a case before dispatch and records an unknown outcome as a
terminal local state. A timeout, disconnect, parse failure, or process crash is
never automatically replayed. Private case JSON includes the generated request,
native CPA, CPAMP event, lineage, and Langfuse identifiers; stdout contains only
fixed aggregate facts. The private directory and files are owner-only.

Cases cover non-streaming, streaming, function tools, synthetic image input,
and bounded cancellation. Successful cases require HTTP 200, preserved
Responses semantics, a full UUIDv7 `X-CPA-TRACE-ID`-derived native binding, an
exact CPAMP event-hash read through the analytics API, separate group/key
ownership, and repeat-read stability. Cancellation records the native binding
and gateway cancellation, but does not require or invent a CPAMP event.

The optional `readback` command verifies one metadata-only immutable Langfuse
generation per completed/cancelled request. It requires no human `userId`,
preserves safe application/group/native ID metadata, rejects prompt/output and
unproven usage/cost, and checks the worker's asynchronous delivery result.

## Evidence boundary

Observed successful provider cases are live evidence for the selected pinned
CPA v8.0.40 / CPAMP v1.14.9 runtime and the exact two-group gateway path. They do
not prove failover/retry attribution, native-ID collision handling, CPAMP outage
replay, retention/restart completeness, or tenant usage authorization. The
production projection gate remains disabled because the required independently
reviewed `correlation` and `durable_history` artifacts do not exist. The worker
readiness check additionally requires one authenticated durable-history read
after restart; a collector health response alone is insufficient.

Do not copy private manifests, tokens, client keys, response bodies, raw CPAMP
rows, Langfuse credentials, or generated identifiers into Git, logs, issues, or
the repository evidence directory.
