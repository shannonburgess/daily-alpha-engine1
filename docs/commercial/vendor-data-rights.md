# Vendor Data Rights and Redistribution Gate

Status: **commercial readiness / no-launch control**

This document defines a provider-neutral control for third-party data rights used by Daily Alpha Research and related Convex Ridge research workflows. It is not legal advice and does not claim that any current subscription permits or prohibits a particular commercial use. Published terms are evidence inputs only; executed agreements, written vendor permission, and external counsel/compliance review remain authoritative for launch decisions.

Tracks #159, #81, #97, #103 and #116.

## Why this gate exists

Daily Alpha can be technically reproducible and still be commercially unlaunchable if customer-facing output depends on data that is licensed only for personal/internal use or cannot be redistributed. This gate separates **internal research permission** from **customer/public display and redistribution permission**.

As reviewed on 2026-08-18, the public OVTLYR Terms of Use describe a limited license for personal, non-commercial use and restrict reproduction/distribution/public display/derivative use except as expressly authorized. ORATS' published Research & Informational Services Agreement describes internal/designated-user use and restricts distribution/redistribution absent written consent. ORATS also notes separate live-data agreements. These public pages do not reveal any separate enterprise/commercial agreement the account holder may have, so the project must record those sources as `RIGHTS_UNVERIFIED` until contract evidence is attached to the registry.

Official public references:
- https://console.ovtlyr.com/terms-of-use
- https://orats.com/terms-conditions
- https://orats.com/legal
- https://orats.com/docs/authentication

## Rights states

Every source/product must have exactly one commercial rights state:

- `VERIFIED_COMMERCIAL` — executed/written evidence supports the specific planned commercial surfaces.
- `VERIFIED_INTERNAL_ONLY` — use is verified for internal research but not customer/public distribution.
- `WRITTEN_PERMISSION_REQUIRED` — published/executed terms indicate separate permission is needed for the planned surface.
- `RIGHTS_UNVERIFIED` — rights have not been established for the proposed use.
- `EXPIRED` — previously verified evidence is no longer current or has passed its re-review date.

`UNKNOWN`, blank, or inferred rights are never treated as commercial approval.

## Registry contract

A versioned machine-readable registry should eventually exist at a stable repository path and contain, at minimum:

```yaml
source_id: ORATS_DATA_API
vendor: ORATS
product: Data API
account_tier: UNKNOWN
rights_state: RIGHTS_UNVERIFIED
terms_reviewed_at: 2026-08-18
terms_url: https://orats.com/terms-conditions
executed_agreement_ref: null
written_permission_ref: null
internal_use: UNKNOWN
commercial_derived_output: UNKNOWN
raw_redistribution: UNKNOWN
chart_display: UNKNOWN
screenshot_display: UNKNOWN
cache_storage: UNKNOWN
post_termination_retention: UNKNOWN
third_party_exchange_restrictions: UNKNOWN
required_attribution: UNKNOWN
allowed_surfaces: []
blocked_surfaces:
  - CUSTOMER_NEWSLETTER
  - CUSTOMER_DASHBOARD
  - DOWNLOADABLE_CSV
  - PUBLIC_SAMPLE
  - MARKETING
review_owner: UNASSIGNED
legal_review_status: NOT_REVIEWED
re_review_at: null
notes: "Published terms reviewed; separate commercial rights not established."
```

The same schema applies separately to each materially different product, feed, exchange entitlement, or contract.

## Minimum source inventory

The registry must cover at least:

- OVTLYR web/export data;
- ORATS delayed/live/historical/derived/intraday products separately where rights differ;
- OPRA or other exchange pass-through rights connected to ORATS live/options data;
- SEC/EDGAR filings and document-derived fields;
- FRED / U.S. Treasury public macro and rate data;
- market-price/history provider(s);
- index/ETF constituent or benchmark data providers;
- email/report delivery provider;
- cloud/database/storage providers where customer data is processed;
- analytics/telemetry providers;
- any future AI/model/data provider whose terms affect output or training/evaluation use.

## Field-level lineage requirement

Every customer-visible report field or section must be traceable to its upstream `source_id` set through the provenance manifest. A rights check evaluates the *planned output surface*, not merely whether the raw field itself is visible.

Examples:

- A raw OVTLYR score shown in a paid dashboard requires explicit rights for that display.
- A Daily Alpha classification derived from OVTLYR may still require commercial derivative permission; transformation alone is not evidence of permission.
- An ORATS option contract quote or chain excerpt requires data/display rights appropriate to the customer surface and applicable exchange agreements.
- A Daily Alpha proprietary signal that uses an internal-only source may be customer-safe only after the right to distribute that derived output is independently verified.

## Fail-closed publication policy

Commercial publication must be blocked when any required upstream source is:

- `RIGHTS_UNVERIFIED`;
- `VERIFIED_INTERNAL_ONLY` for the requested surface;
- `WRITTEN_PERMISSION_REQUIRED` without attached permission evidence;
- `EXPIRED`;
- missing from the registry;
- affected by a contract/terms change that has not been re-reviewed.

The correct fallback is to omit/disable the affected commercial surface or keep the artifact internal. The system must not silently replace a restricted source with a different vendor or downgrade provenance.

## Derived-output minimization

Even after rights are verified, customer outputs should minimize unnecessary vendor raw-data exposure:

- prefer Daily Alpha's own signal state, reason codes and model explanations where permitted;
- do not expose API tokens, endpoint payloads, raw chains, proprietary vendor screenshots or bulk exports unless the contract explicitly permits that surface;
- provenance should name the source and evidence version without embedding restricted raw material;
- downloadable/export APIs need a stricter rights check than a rendered narrative report;
- public sample reports and marketing screenshots are separate surfaces and require separate approval.

## Contract-change control

A terms or executed-agreement change must create a re-review event. The source moves to `RIGHTS_UNVERIFIED` or `EXPIRED` for affected commercial surfaces until reviewed. This control must be independent from internal research so a rights review can disable publication without corrupting historical research or signal generation.

## Test requirements

Before commercial beta, automated tests should prove:

1. missing registry entry blocks customer publication;
2. `RIGHTS_UNVERIFIED` blocks customer publication;
3. `VERIFIED_INTERNAL_ONLY` permits internal research but blocks customer/public surfaces;
4. expired rights block affected surfaces;
5. `VERIFIED_COMMERCIAL` is surface-specific and does not imply blanket redistribution permission;
6. provenance manifests can reference source IDs without leaking raw licensed content;
7. a rights-state change invalidates/rebuilds affected customer artifacts;
8. public samples, downloadable CSV/API and marketing surfaces are independently gated;
9. no test fixture embeds real vendor tokens or restricted production payloads.

## Commercial beta no-go condition

Daily Alpha commercial beta is **NO-GO** until every source required by the launch scope has current evidence supporting the planned customer/public use and the legal/compliance review gate has recorded the applicable conclusion. Internal research may continue under its separately verified rights boundary.

## Explicit non-actions

This specification does not authorize contacting a vendor, upgrading/purchasing a plan, signing an agreement, publishing customer content, redistributing vendor data, launching a website, or making a legal/compliance claim. Those remain approval-gated external actions.
