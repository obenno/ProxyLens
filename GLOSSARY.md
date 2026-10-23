# ProxyLens

ProxyLens is the tenant-aware integration boundary around authorized model-provider access, usage visibility, and observability.

## Identity and access

**User**:
A human identity that can authenticate and receive permissions in ProxyLens.
_Avoid_: Account, customer, operator (unless the role is specifically meant).

**Group**:
The canonical access and ownership boundary for ProxyLens resources and usage visibility.
_Avoid_: Team, tenant (when referring to the identity-management object).

**Application**:
A client integration that makes model requests on behalf of a group.
_Avoid_: Client, service account (unless referring to an external identity-system object).

**Client key**:
A machine credential issued to one application for authenticating model requests.
_Avoid_: API key, user key (when the credential is specifically a ProxyLens key).

**Platform administrator**:
A user authorized to manage ProxyLens-wide configuration, integrations, and resources across groups.
_Avoid_: Superuser, root.

**Group administrator**:
A user authorized to manage ProxyLens resources owned by groups in which they have administrative membership.
_Avoid_: Team owner.

## Model access and usage

**Provider account**:
An authorized provider credential managed by the provider gateway and used to reach a model subscription or API.
_Avoid_: User account, customer account.

**Model request**:
One client-originated invocation of a model through the ProxyLens gateway.
_Avoid_: Call, transaction.

**Usage record**:
The provider-gateway-derived fact describing a completed or failed model request, including available token, latency, model, provider, and status data.
_Avoid_: Billing record, invoice.

**Usage projection**:
A rebuildable ProxyLens view of authoritative usage records, filtered and attributed for authorized group and application queries.
_Avoid_: Usage ledger, source-of-truth usage record.

**Estimated cost**:
A cost calculation derived from usage and pricing metadata when authoritative provider billing is unavailable.
_Avoid_: Charge, billable amount.

**Policy**:
The set of authorization and traffic constraints applied to a group, application, or client key.
_Avoid_: Configuration (when referring to an access decision).

## Integration and observability

**Correlation**:
The linkage among a ProxyLens request, its provider-gateway request, its usage record, its usage projection, and its observability observation.
_Avoid_: Attribution (when referring to the identifiers and join itself).

**Observation**:
Telemetry describing a model request for monitoring and analysis; it is not an authorization or billing authority.
_Avoid_: Usage record, audit event.

**Orphaned resource**:
A ProxyLens application or client key whose owning group no longer exists in the identity authority.
_Avoid_: Unassigned resource.

**CPAMP**:
CPA-Manager-Plus Full Mode, the designated consumer of CLIProxyAPI usage events and the authoritative source for durable request history and usage analytics.
_Avoid_: ProxyLens collector, usage queue consumer.
