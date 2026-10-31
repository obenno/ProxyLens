from uuid import UUID

import pytest

from proxylens.correlation import (
    CorrelationStatus,
    IngressRequest,
    NativeBinding,
    Ownership,
    UsageIdentity,
    correlate,
    observation_metadata,
    parse_cpa_trace_id,
    propagation_headers,
    returned_cpa_trace,
    tenant_usage_gate,
)


def test_returned_trace_keeps_the_full_native_uuid_not_the_log_suffix():
    trace = parse_cpa_trace_id(
        "20261024000000-aaaaaaaaaaaaaaaa-019a96c4-0c00-7000-8000-0123456789ab"
    )
    assert trace is not None
    assert trace.request_id == UUID("019a96c4-0c00-7000-8000-0123456789ab")


@pytest.mark.parametrize(
    "value",
    [
        None,
        "",
        "client-supplied",
        "20261024000000-a-6789abcd",
        "20261024000000-a-019a96c40c00700080000123456789ab",
        "20261024000000-a-00000000-0000-0000-0000-000000000000",
        "20261024000000-a-019a96c4-0c00-7000-8000-0123456789ab\r\nsecret: token",
        "20261024000000-a-019a96c4-0c00-7000-8000-0123456789ab,second",
        "20261024000000-" + "a" * 1000 + "-019a96c4-0c00-7000-8000-0123456789ab",
        "20261024000000-credential secret-019a96c4-0c00-7000-8000-0123456789ab",
        "２０２６１０２４００００００-a-019a96c4-0c00-7000-8000-0123456789ab",
    ],
)
def test_untrusted_trace_values_are_bounded_rejected_and_not_echoed(value):
    assert parse_cpa_trace_id(value) is None


def test_each_ingress_gets_its_own_id_and_propagates_only_generated_diagnostics():
    owner = Ownership("https://identity.test/realms/proxylens", "g1", "app1", "key1")
    first, second = IngressRequest.new(owner), IngressRequest.new(owner)
    assert first.request_id != second.request_id
    assert first.request_id.version == 4
    assert first.owner == owner
    assert propagation_headers(first) == {"X-Request-ID": str(first.request_id)}
    # No X-Client-Request-Id/Session-Id injection: these affect Codex session affinity.
    assert first.session_id != second.session_id
    assert len(first.trace_id) == 32
    assert len(first.generation_id) == 16


def test_only_one_returned_cpa_header_can_establish_native_identity():
    raw = "20261024000000-a-019a96c4-0c00-7000-8000-0123456789ab"
    assert returned_cpa_trace([("x-CpA-TrAcE-Id", raw)]).request_id == UUID(
        "019a96c4-0c00-7000-8000-0123456789ab"
    )
    assert returned_cpa_trace([("X-Request-ID", raw), ("response.id", raw)]) is None
    assert returned_cpa_trace([("X-CPA-TRACE-ID", raw), ("x-cpa-trace-id", raw)]) is None


def test_retry_events_keep_distinct_hashes_but_same_exact_owner():
    request = IngressRequest.new(Ownership("issuer", "g1", "app1", "key1"))
    native = UUID("019a96c4-0c00-7000-8000-0123456789ab")
    binding = NativeBinding("cpa1", native, request)
    failed = UsageIdentity("cpamp1", "a" * 64, "cpa1", native)
    succeeded = UsageIdentity("cpamp1", "b" * 64, "cpa1", native)
    results = [correlate(event, [binding]) for event in (failed, succeeded)]
    assert [result.status for result in results] == [CorrelationStatus.CORRELATED] * 2
    assert [result.event.event_hash for result in results] == ["a" * 64, "b" * 64]
    assert all(result.ingress == request for result in results)


@pytest.mark.parametrize("same_owner", [False, True])
def test_native_collision_is_ambiguous_even_for_two_requests_of_one_owner(same_owner):
    first = IngressRequest.new(Ownership("issuer", "g1", "app1", "key1"))
    second = IngressRequest.new(
        first.owner if same_owner else Ownership("issuer", "g2", "app2", "key2")
    )
    native = UUID("019a96c4-0c00-7000-8000-0123456789ab")
    event = UsageIdentity("cpamp1", "a" * 64, "cpa1", native)
    bindings = [NativeBinding("cpa1", native, request) for request in (first, second)]
    result = correlate(event, bindings)
    assert result.status == CorrelationStatus.AMBIGUOUS
    assert result.ingress is None


def test_absent_native_ids_and_unmatched_instances_never_guess_owners():
    request = IngressRequest.new(Ownership("issuer", "g1", "app1", "key1"))
    native = UUID("019a96c4-0c00-7000-8000-0123456789ab")
    bindings = [NativeBinding("cpa1", native, request)]
    missing = correlate(UsageIdentity("cpamp1", "a" * 64, "cpa1", None), bindings)
    other = correlate(UsageIdentity("cpamp2", "b" * 64, "cpa2", native), bindings)
    assert (missing.status, missing.ingress) == (CorrelationStatus.MISSING, None)
    assert (other.status, other.ingress) == (CorrelationStatus.PARTIAL, None)


def test_telemetry_allowlists_ids_and_cannot_attach_another_requests_usage():
    request = IngressRequest.new(Ownership("issuer", "g1", "app1", "key1", "verified-subject"))
    other = IngressRequest.new(Ownership("issuer", "g2", "app2", "key2"))
    trace = parse_cpa_trace_id(
        "20261024000000-PRIVATE_AUTH_INDEX-019a96c4-0c00-7000-8000-0123456789ab"
    )
    event = UsageIdentity("cpamp1", "a" * 64, "cpa1", trace.request_id)
    result = correlate(event, [NativeBinding("cpa1", trace.request_id, request)])
    metadata = observation_metadata(request, result)
    assert metadata["keycloak_group_id"] == "g1"
    assert metadata["cpa_request_id"] == "019a96c4-0c00-7000-8000-0123456789ab"
    assert metadata["cpamp_event_hash"] == "a" * 64
    assert metadata["correlation_status"] == "correlated"
    assert metadata["user_id"] == "verified-subject"
    assert metadata["trace_id"] == request.trace_id
    assert "PRIVATE_AUTH_INDEX" not in str(metadata)
    assert "client_key_id" not in metadata
    with pytest.raises(ValueError, match="lineage ownership mismatch"):
        observation_metadata(other, result)
    assert observation_metadata(request)["correlation_status"] == "partial"


def test_tenant_usage_gate_cannot_be_enabled_by_local_or_history_only_evidence(monkeypatch):
    monkeypatch.setenv("PROXYLENS_CORRELATION_PROVEN", "true")
    for history_proven in (False, True):
        gate = tenant_usage_gate(durable_history_proven=history_proven)
        assert gate.enabled is False
        assert "correlation_live_proof_missing" in gate.blockers
        assert ("cpamp_live_proof_missing" in gate.blockers) is (not history_proven)


def test_gateway_can_export_returned_id_before_cpamp_arrives_without_exporting_auth_index():
    request = IngressRequest.new(Ownership("issuer", "g1", "app1", "key1"))
    native = UUID("019a96c4-0c00-7000-8000-0123456789ab")
    metadata = observation_metadata(request, binding=NativeBinding("cpa1", native, request))
    assert metadata["cpa_request_id"] == "019a96c4-0c00-7000-8000-0123456789ab"
    assert metadata["correlation_status"] == "partial"
    assert "cpamp_event_hash" not in metadata
    assert "user_id" not in metadata  # machine identity must not become key creator identity
    other = IngressRequest.new(Ownership("issuer", "g2", "app2", "key2"))
    with pytest.raises(ValueError, match="lineage ownership mismatch"):
        observation_metadata(request, binding=NativeBinding("cpa1", native, other))


def test_invalid_contract_values_fail_without_echoing_secrets():
    from dataclasses import replace

    request = IngressRequest.new(Ownership("issuer", "g1", "app1", "key1"))
    secret = "\r\nAuthorization: Bearer NEVER_ECHO"
    with pytest.raises(ValueError) as error:
        replace(request, request_id=secret)
    assert "NEVER_ECHO" not in str(error.value)
    with pytest.raises(ValueError) as error:
        UsageIdentity("cpamp1", secret, "cpa1", None)
    assert "NEVER_ECHO" not in str(error.value)
    with pytest.raises(ValueError) as error:
        Ownership("issuer", secret, "app1", "key1")
    assert "NEVER_ECHO" not in str(error.value)


def test_duplicate_binding_evidence_is_not_a_second_owner():
    request = IngressRequest.new(Ownership("issuer", "g1", "app1", "key1"))
    native = UUID("019a96c4-0c00-7000-8000-0123456789ab")
    binding = NativeBinding("cpa1", native, request)
    result = correlate(UsageIdentity("cpamp1", "a" * 64, "cpa1", native), [binding, binding])
    assert (result.status, result.ingress) == (CorrelationStatus.CORRELATED, request)


def test_maximum_accepted_trace_is_bounded_and_private_fields_are_not_printed():
    raw = "20261024000000-" + "a" * 64 + "-019a96c4-0c00-7000-8000-0123456789ab"
    trace = parse_cpa_trace_id(raw)
    assert trace is not None
    assert "a" * 64 not in repr(trace)
    assert raw not in repr(trace)
    assert parse_cpa_trace_id(raw.replace("a" * 64, "a" * 65)) is None
