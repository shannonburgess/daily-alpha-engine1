# Performance Evidence and Marketing-Claim Governance

Status: commercial-beta readiness design only. This document does **not** determine Daily Alpha's regulatory status and is **not** legal advice or legal approval.

## Objective

Prevent customer-facing Daily Alpha materials from presenting unsupported, stale, cherry-picked, or ambiguously labeled performance information. The repository should preserve a reproducible evidence chain before any claim reaches external legal/compliance review.

## Evidence classes

Every performance record must be exactly one of:

- `ACTUAL` — based only on user-confirmed/executed activity with auditable fills and costs.
- `PAPER` — forward paper-account results; never described as live performance.
- `BACKTEST` — historical simulation using documented point-in-time inputs and assumptions.
- `HYPOTHETICAL` — model/scenario output that is not an actual or forward paper result.

A single claim must not blend evidence classes. Multiple classes may appear in one report only as separately labeled sections with separate statistics and limitations.

## Required lineage

Each evidence item must preserve:

1. stable evidence ID;
2. basis/class;
3. metric name and measured period;
4. `as_of` timestamp;
5. methodology/model version;
6. content/source hash for the canonical underlying record set;
7. sample size;
8. gross and/or net result;
9. assumptions and limitations, mandatory for backtest/hypothetical evidence.

## Claim registry

Every proposed external claim should have:

- stable claim ID and exact claim text;
- intended channel and audience;
- evidence IDs;
- displayed evidence basis;
- material risks and limitations;
- creation and expiration/revalidation date;
- review state;
- external-review reference before external use.

Changing a material methodology, calculation, fee assumption, data source, sample, or claim wording should invalidate the prior review and require a new evidence/review record.

## Fail-closed publication gate

The repository gate should block an external claim when:

- evidence is missing;
- more than one performance basis is combined into a single claim;
- the displayed basis does not match the evidence;
- the claim has expired;
- evidence limitations are missing;
- hypothetical/backtest assumptions are missing;
- external review is incomplete or lacks an auditable review reference.

Passing the repository gate does **not** establish that the claim is legally permissible. External counsel/compliance review remains a separate launch requirement.

## Regulatory-perimeter questions for external counsel

Before a commercial beta or public website uses securities research, model portfolios, recommendations, or performance, obtain external advice on at least:

- whether Daily Alpha or any planned entity is an investment adviser, publisher, broker-dealer, commodity trading adviser, or falls within another federal/state regulatory perimeter;
- whether any publisher exclusion or other exclusion/exemption is available given the exact product, personalization, cadence, compensation, and customer relationship;
- which advertising/marketing, books-and-records, testimonial/endorsement, performance, privacy, communications-retention, and state requirements apply;
- whether customer-specific portfolio outputs or brokerage integrations change the analysis;
- what disclosures, contracts, registrations, licenses, supervisory procedures, and record-retention controls are required before launch.

Do not encode a legal conclusion in product logic. Encode only the requirement that external review be complete before customer-facing claims are released.

## Official source anchors for counsel/review

The following are source anchors, not an assertion that a specific rule applies to Daily Alpha:

- SEC Investment Adviser Marketing compliance guide: https://www.sec.gov/resources-small-businesses/small-business-compliance-guides/investment-adviser-marketing
- SEC Marketing Compliance FAQs: https://www.sec.gov/rules-regulations/staff-guidance/division-investment-management-frequently-asked-questions/marketing-compliance-frequently-asked-questions
- SEC Division of Examinations Marketing Rule risk alert (April 17, 2024): https://www.sec.gov/compliance/risk-alerts/risk-alert-041724
- SEC enforcement example regarding public hypothetical performance (August 9, 2024): https://www.sec.gov/enforcement-litigation/administrative-proceedings/ia-6646-s

## Commercial-beta acceptance criteria

- No customer-facing performance claim can bypass the evidence registry.
- Actual, paper, backtest, and hypothetical results remain separately labeled and queryable.
- Claim evidence can be reproduced from immutable inputs and a methodology version.
- Claim review expires and can be invalidated by material methodology changes.
- Customer-facing release remains blocked until external legal/compliance review is documented.
- No repository status or automated test may be described as regulator approval.
