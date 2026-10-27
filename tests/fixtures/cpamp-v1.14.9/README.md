# CPAMP v1.14.9 fixtures

`analytics.json` is the first-page response from the official released binary's
isolated synthetic HTTP experiment. `export.jsonl` contains its three export rows.
Only formatting changed; values were fictional at import (no provider traffic).
These preserve the important surface difference: analytics `cached_tokens=0`,
export `cached_tokens=20`, and both `cache_read_tokens=20`.

Evidence origin: `/data/tmp/opencode/proxylens-phase1/http-proof/results.json` from
the upstream-contract investigation. Source commit:
`seakee/CPA-Manager-Plus@6d962db680085827cd19a778d2ff05a3d1315672`.
The archive SHA-256 and a repeatable binary exercise are in
`docs/cpamp-contract.md` and `scripts/cpamp-read-poc.py`.

Tests load a fresh fixture per scenario and alter it explicitly for error cases.
Synthetic variants are tests of adapter behavior, not claims about actual upstream
responses. The POC imports these portable rows into a new scratch server, moves
their timestamps into the past, and exercises the production HTTP adapter.

These fixtures do not prove a provider request, collector consumption, arbitrary
ingress-ID propagation, or original CPA canonical token accounting.
