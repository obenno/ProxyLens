# LiteLLM for per-user CPAMP-style dashboards

Research date: October 29, 2026. Requirement: subscription-to-API access,
per-user usage management and personal statistics, with Langfuse observability.
This is source/documentation research; no deployment or provider calls were made.

For the consolidated recommendation, proposed ownership contracts, existing-issue
mapping and runtime acceptance gates, see the
[architecture research handoff](architecture-handoff-2026-10-29.md).

## Product-fit conclusion

LiteLLM is a credible foundation for a custom per-user CPAMP-style stats product:
the project documents both dashboard embedding and ordinary request callbacks,
plus a native Langfuse integration. These extension points address the earlier
comparison's dashboard/export integration gaps. This is a source-supported product
fit judgment, not proof of complete CPAMP parity or a migration decision.
[plugins] [hooks] [langfuse]

Prefer existing personal usage views for the first POC. Build a separate scoped
analytics UI/backend for the exact panels the user needs; consider embedding that
UI only after testing non-admin access. Keep provider OAuth and pooling in the
already exercised CPA runtime initially. An integrated dashboard plugin is useful,
but the durable stats contract and user isolation remain backend responsibilities.

## Evidence snapshot

GitHub's latest-release API returned **v1.106.6**, published October 28, 2026
at 23:03:09 UTC, commit `61c6ab78393ef45683dd7d963d2a315bd845e20b`.
Live documentation may describe later versions; release-specific conclusions must
be checked against pinned source. [release]

## Proposed composition with the existing provider runtime

```text
Client → LiteLLM → CLIProxyAPI → authorized provider subscription
             ├→ personal usage data → custom analytics backend/UI
             └→ native Langfuse callback
```

LiteLLM documents Responses forwarding through an `openai/` model with a custom
`api_base`. That supports the proposed CPA composition, but does not prove actual
client compatibility. Preserve the native Responses route instead of assuming a
chat-completions bridge is equivalent. Streaming, tools, images, continuation,
cancellation and usage reconciliation need testing on the selected pair. [responses]
The pinned OpenAI Responses adapter constructs `{api_base}/responses`, confirming
custom-base support in the inspected release. [responses-source]

Under this proposal LiteLLM owns authenticated requesting-user/key attribution.
Retain CPAMP only where provider-account diagnostics are wanted, as the sole CPA
usage-queue consumer. A personal dashboard should not require a CPAMP join for every
request. Provider attempts and client requests remain distinct accounting concepts.

## Native personal usage and identity

LiteLLM documents two relevant dashboard roles: `internal_user` can manage its own
keys and view its spend; `internal_user_viewer` can view its own keys/spend without
creating or deleting keys. Virtual keys can belong to a user, team or both. For the
requested personal dashboard, assign each human an internal user and user-owned
keys; aggregate all their keys under the stable user ID. [self-serve] [rbac]

The self-serve guide also suggests Admin Viewer for its Usage/Caching Analytics
walkthrough. That role sees all keys/spend according to the same guide. Do not use
it as a shortcut to give each user a personal CPAMP-like dashboard. [self-serve]

The separate Customer Usage feature tracks an end-user/customer identifier supplied
in the request body or headers and presents it in administrator analytics. That
label is not a dashboard login or an authenticated user ownership boundary.
It is useful for applications with downstream customers, but does not replace
the user/key mapping needed here. [customer-usage]

Native Logs UI documents per-request spend, token usage, key and team information,
with success and error records enabled by default and prompt/response storage
disabled by default. This establishes a useful request-history baseline, not every
CPAMP-style personal percentile/heatmap/throughput panel. [logs]

Pinned source provides stronger evidence of personal scoping: ordinary-user daily
activity resolves to the authenticated user and rejects another user's ID. Log
list/detail access also applies user/authorized-team scopes. Extra team permissions
can broaden access, so own-only behavior depends on the assigned role. [user-api]
[daily-scope] [spend-api]

| Requested statistics | Verified native implementation | Additional work for the requested presentation |
|---|---|---|
| Requests, input/output/total tokens, model/key spend | Personal activity charts and request detail. [activity-ui] [detail-ui] | CPAMP-specific layout and additional filtering. |
| Cache read/write | Daily cache-token charts and request details. [activity-ui] [detail-ui] | Distinguish provider prompt cache from LiteLLM response-cache hits. |
| Reasoning tokens | Request detail when supplied and positive. [detail-ui] | No dedicated daily-user reasoning aggregate verified; custom time-series aggregation. [spend-schema] |
| Latency/errors | Average response-time and success/failure charts, request errors. [activity-ui] [detail-ui] | Personal percentiles/heatmaps; validate captured failure coverage. |
| TTFT | Individual request detail from first-token/start timestamps. [detail-ui] | Personal TTFT distributions/percentiles. |
| RPM/TPM | Configured limits and daily totals. [activity-ui] | Measured per-minute throughput charts were not verified; derive from timestamped scoped events. |

The official edition comparison lists virtual keys, budgets/rate limits, spend
tracking and the Admin UI in the open-source gateway. Enterprise adds capabilities
including SSO/SCIM, audit logs, delegated organizational administration and per-team
logging. This does not mean every advanced analytics route or historical range is
available without a license; check the selected release's actual endpoint gates
before promising an OSS-only implementation. [editions]

Specific gates verified: dashboard SSO is free for up to five users, with an
Enterprise license required beyond that; direct IdP-JWT gateway authentication is
a separate premium feature. `/global/spend/report` and scoped spend-report routes
check premium status, while ordinary self-scoped daily activity is a different API.
These gates do not make all personal analytics Enterprise. [sso] [jwt-auth]
[spend-api] [user-api]

## Custom dashboard architecture

Dashboard plugins were verified in v1.106.6. An external service
supplies its own backend, manifest and iframe UI; LiteLLM supplies navigation and a
short-lived identity claim containing internal user ID and role. This supports
embedding a custom reporting product without maintaining a complete frontend fork.
It is not a drag-and-drop chart builder or automatic authorization for plugin data.
[plugins]

The docs state a v1.89.3 minimum, but that minimum was not confirmed: the inspected
plugin-route path was absent at several early tags. Use the verified release
snapshot rather than the documentation's minimum as the deployment claim.
No premium/license check was found in the inspected plugin backend, loading or UI;
those files are outside the repository's Enterprise license carve-out. External
plugins have their own licensing. [plugin-source] [license]

The CPAMP comparison target is its request/token/cost/failure/latency overview,
model/key rankings, time trends, heatmaps and request drill-down. Its provider
credential rankings and quota inspection are a separate operator surface. An
upstream LiteLLM gateway sees its configured CPA deployment; it cannot infer the
particular CPA provider credential or hidden provider attempts from that deployment
alone. Keep that distinction when describing dashboard parity. [cpamp]

There is a relevant restriction: the documented `/plugin-proxy/{name}/{path}` route
is restricted to `proxy_admin`. Treat plugin discovery, direct iframe rendering,
identity claims and proxied backend access as separate capabilities. A personal
dashboard for ordinary users needs its own authenticated backend/session and scoped
data queries, or a specifically verified supported integration path; enabling a
plugin alone does not prove that user flow works. [plugins]

Additionally, the pinned central ordinary-user route allowlists omit plugin
discovery/auth-token routes. **Static-source inference:** normal-user plugin entry
may require configuration or an upstream change; do not promise turnkey personal
plugin access before testing it. This concern does not apply to the explicitly
allowed native personal usage routes. The plugin reverse proxy forwards to the
plugin service, not back into LiteLLM analytics with delegated user credentials.
[plugin-source] [route-checks] [route-types]

For a CPAMP-style product, the proposed custom UI would combine per-user totals,
time/model/key trends, cache/reasoning breakdowns where available, error rates,
latency/first-token distributions and request drill-down. Use built-in scoped
usage APIs where they retain the needed data; capture missing fields through
documented callbacks into an asynchronous stats pipeline. LiteLLM's hook interface
receives authenticated key information, making trusted user attribution available
without rebuilding provider forwarding. [payload] [hooks]

Proposed dashboard data contract (design, not an existing LiteLLM endpoint):

| Panel | Input and semantics |
|---|---|
| Personal totals and per-key trends | Trusted internal user ID plus all owned key IDs; one agreed request-level event identity. |
| Token breakdown | Preserve upstream usage and normalize exclusive input/cache/output/reasoning buckets once. Unknown is not zero. |
| Cost | Label model-price estimate separately from internal budget consumption and the actual subscription invoice. |
| Latency and TTFT | Derive total latency from end minus start; TTFT from first-token timestamp minus start. The documented streaming `response_time` represents TTFT, so it must not be relabeled total duration. [payload] |
| Success/failure and retries | Keep terminal client-request outcome separate from deployment-attempt failures and authentication/admission rejections. |
| Heatmap and percentile panels | Aggregate retained request-level events under the same user/time/model filters as the totals. |

This is the proposed remaining custom surface: event persistence/aggregation where
native APIs are insufficient, user-scoped reads, and presentation. Provider OAuth,
forwarding, key lifecycle and Langfuse transport should be reused from the selected
components rather than recreated in the dashboard service.

Pinned `CustomLogger` source distinguishes request-level failure logging from
deployment-attempt failure hooks, useful for measuring LiteLLM's own retries and
fallbacks. It cannot expose retries hidden inside a single upstream CPA request
without separate CPA evidence. [callback-source]

## Langfuse is an existing integration

LiteLLM has native `langfuse` and `langfuse_otel` callbacks. Langfuse's own guide
documents `callbacks: ["langfuse_otel"]`. User/session metadata can be supplied,
and LiteLLM documents message redaction while retaining usage/cost metadata.
This is an existing integration, not a proposed exporter fork. [langfuse] [logging]

Pinned source includes the SDK-based and OTEL-based implementations. Background
delivery does not establish a transactional outbox, lossless crash recovery or
exactly-once ingestion. Verify those properties only to the level required by the
product; do not use Langfuse as the personal accounting authority. [langfuse-source]

For personal attribution, explicitly map the trusted key-owner identity to the
Langfuse user. The documented `trace_user_id` defaults to the completion's `user`
argument; the proxy's `user_api_key_user_id` is a separate field. A caller-provided
end-user string is not proof of dashboard ownership. [langfuse-identity] [payload]

The standard payload exposes status, input/output totals, start/end/first-token
timestamps, key-owner metadata and optional raw `usage_object`. These provide a
documented collection surface for a custom stats service. Presence in callback
payloads alone does not prove persistence or ready-made charts for every field.
Cache and reasoning cost components can be subsets of input/output cost; avoid
double-counting. [payload]

LiteLLM documents that spend-log metadata can retain `usage_object`,
`cost_breakdown` and error details. Metadata filtering can remove these fields,
disabling corresponding historical details. Any custom dashboard must pin and
validate its storage/read contract rather than assume the callback's full payload
is always present in the database. [logs]

## Subscription support qualification

Do not infer that LiteLLM never supports subscriptions. Its live subscription page
describes Claude, Codex and Copilot flows, each developer connecting their own
account. However, the page labels Codex `v1.109.0+` and Copilot `v1.108.0+`, beyond
the release snapshot above. That page does not establish those features in
v1.106.6 or parity with CPA's account-pool behavior. The CPA-retaining composition
is therefore the relevant initial candidate for this dashboard assessment.
[subscriptions]

## Focused acceptance criteria

The following would answer the remaining implementation questions; none were run:

1. Two ordinary dashboard users, multiple keys each, one shared CPA upstream.
   Confirm own totals, own request details and cross-user access rejection.
2. Evaluate the exact OSS or licensed image selected: personal usage routes, log
   history, long date ranges and plugin visibility/proxying under both normal-user
   roles. Do not infer backend authorization from sidebar visibility.
3. Compare a normal response, SSE response, tool round-trip, image request,
   cache/reasoning response, failure and cancellation against the persisted stats.
4. Verify the chosen custom reporting session binds queries to the logged-in
   internal user, and cannot switch ownership through a URL parameter or request
   `user` field. Verify corresponding Langfuse user attribution.
5. Restart the gateway and stats collector; inspect telemetry loss/delay and replay
   behavior. Distinguish provider-reported usage, estimates and unknown usage.

## Sources

[release]: https://github.com/BerriAI/litellm/releases/tag/v1.106.6
[responses]: https://docs.litellm.ai/docs/response_api
[langfuse]: https://langfuse.com/integrations/gateways/litellm
[logging]: https://docs.litellm.ai/docs/proxy/logging
[langfuse-source]: https://github.com/BerriAI/litellm/blob/61c6ab78393ef45683dd7d963d2a315bd845e20b/litellm/integrations/langfuse/langfuse.py
[langfuse-identity]: https://docs.litellm.ai/docs/observability/langfuse_integration
[payload]: https://docs.litellm.ai/docs/proxy/logging_spec
[subscriptions]: https://docs.litellm.ai/docs/subscriptions
[plugins]: https://docs.litellm.ai/docs/proxy/plugins
[hooks]: https://docs.litellm.ai/docs/proxy/call_hooks
[callback-source]: https://github.com/BerriAI/litellm/blob/61c6ab78393ef45683dd7d963d2a315bd845e20b/litellm/integrations/custom_logger.py#L303-L337
[logs]: https://docs.litellm.ai/docs/proxy/ui_logs
[responses-source]: https://github.com/BerriAI/litellm/blob/61c6ab78393ef45683dd7d963d2a315bd845e20b/litellm/llms/openai/responses/transformation.py#L654-L673
[cpamp]: https://seakee.github.io/CPA-Manager-Plus/docs/en/manual/usage-analytics.html
[self-serve]: https://docs.litellm.ai/docs/proxy/self_serve
[rbac]: https://docs.litellm.ai/docs/proxy/access_control
[customer-usage]: https://docs.litellm.ai/docs/proxy/customer_usage
[editions]: https://docs.litellm.ai/docs/enterprise
[user-api]: https://github.com/BerriAI/litellm/blob/61c6ab78393ef45683dd7d963d2a315bd845e20b/litellm/proxy/management_endpoints/internal_user_endpoints.py#L2880-L3018
[daily-scope]: https://github.com/BerriAI/litellm/blob/61c6ab78393ef45683dd7d963d2a315bd845e20b/litellm/proxy/management_endpoints/daily_activity_scopes.py
[spend-api]: https://github.com/BerriAI/litellm/blob/61c6ab78393ef45683dd7d963d2a315bd845e20b/litellm/proxy/spend_tracking/spend_management_endpoints.py
[activity-ui]: https://github.com/BerriAI/litellm/blob/61c6ab78393ef45683dd7d963d2a315bd845e20b/ui/litellm-dashboard/src/components/activity_metrics.tsx#L250-L387
[detail-ui]: https://github.com/BerriAI/litellm/blob/61c6ab78393ef45683dd7d963d2a315bd845e20b/ui/litellm-dashboard/src/components/logs/detail/LogDetailContent.tsx#L469-L575
[spend-schema]: https://github.com/BerriAI/litellm/blob/61c6ab78393ef45683dd7d963d2a315bd845e20b/schema.prisma#L850-L886
[sso]: https://docs.litellm.ai/docs/proxy/admin_ui_sso
[jwt-auth]: https://github.com/BerriAI/litellm/blob/61c6ab78393ef45683dd7d963d2a315bd845e20b/litellm/proxy/auth/user_api_key_auth.py#L1680-L1720
[plugin-source]: https://github.com/BerriAI/litellm/blob/61c6ab78393ef45683dd7d963d2a315bd845e20b/litellm/proxy/plugin_routes.py
[license]: https://github.com/BerriAI/litellm/blob/61c6ab78393ef45683dd7d963d2a315bd845e20b/LICENSE
[route-checks]: https://github.com/BerriAI/litellm/blob/61c6ab78393ef45683dd7d963d2a315bd845e20b/litellm/proxy/auth/route_checks.py#L264-L369
[route-types]: https://github.com/BerriAI/litellm/blob/61c6ab78393ef45683dd7d963d2a315bd845e20b/litellm/proxy/_types.py#L865-L1038
