# ProxyLens

ProxyLens integrates authorized model-provider access, usage visibility, and
observability. Current-runtime terms and adopted target personal-usage terms are
separated below. [ADR 0001](docs/adr/0001-architecture-boundaries.md) remains the
checked-in runtime contract until separately approved cutover; [ADR 0002](docs/adr/0002-litellm-personal-usage.md)
is the accepted target architecture.

## Current implementation: identity and access

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

## Current implementation: model access and usage

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

## Current implementation: integration and observability

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

## Adopted target: personal ownership

**Platform user**:
A stable personal identity that owns access credentials and personal usage.
_Avoid_: Customer, provider account.

**Personal key**:
A machine credential owned by one platform user, typically for one client integration.
_Avoid_: Provider credential, shared application key.

**Key owner**:
The platform user responsible for an authenticated personal key's usage.
_Avoid_: Interactive actor, key creator.

**Interactive actor**:
A human whose identity was verified for the particular interaction.
_Avoid_: Key owner (when only machine-credential ownership is known).

**Customer label**:
An application-supplied end-user identifier, separate from platform ownership.
_Avoid_: Authenticated user, trusted owner.

**Ownership attribution**:
Assignment of a request's usage to its responsible owner, with the basis identified.
_Avoid_: Correlation, proof of human presence.

## Adopted target: request accounting

**Client request**:
One model invocation submitted by a client to the gateway, distinct from gateway/provider attempts made to execute it. A client retry submitted as a new request is a separate client request; one user action may produce several.
_Avoid_: User action, provider attempt, gateway attempt.

**Gateway attempt**:
One execution attempt made by the client-facing gateway for a client request.
_Avoid_: Client request, provider attempt (when internal provider execution is unknown).

**Provider attempt**:
One execution attempt against a provider; one client request can require several.
_Avoid_: Personal request, inferred retry.

**Client-request fact**:
A retained measurement or outcome associated with a client request and its admitted owner.
_Avoid_: Observation, subscription invoice.

**Personal usage projection**:
A user-scoped derived view that can be rebuilt from retained client-request facts.
_Avoid_: Independent usage ledger, callback archive (without a retained source).

**Estimated API-equivalent cost**:
A usage-based estimate using a specified model-price table and currency.
_Avoid_: Subscription charge, actual bill.

**Allowance consumption**:
The amount counted against an internal usage budget under its selected rules and units.
_Avoid_: Provider payment, estimated cost (unless the policy explicitly equates them).

**Subscription expenditure**:
The actual amount paid for provider subscription access.
_Avoid_: Per-request token estimate.

**Accounting epoch**:
A period whose usage shares a defined ownership and accounting contract.
_Avoid_: Budget reset period.

## Adopted target: debugging observability

**Debugging trace**:
Request/session observations containing available transmitted prompts/code, AI outputs, visible tool interactions, errors and execution measurements for application diagnosis. It is not a record of local execution or files never transmitted.
_Avoid_: Complete local-agent record, authoritative usage ledger.

**Trace attribution**:
Association of observations with an owner and session for analysis; it does not grant permission to read those observations.
_Avoid_: Trace access authorization, proof of interactive actor.
