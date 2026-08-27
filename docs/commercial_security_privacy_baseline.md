# Daily Alpha Commercial Security & Privacy Baseline

Status: **internal design / staging only**  
Tracks: #81, #103  
Safety boundary: this document does not authorize customer launch, payment processing, public publication, production deployment, TradingView mutation, or live trading.

## Purpose

Daily Alpha's commercial beta adds authenticated users, customer metadata, entitlement state, delivery history, support/admin access, billing-event projections, research outputs, performance evidence, and internet-facing application/API surfaces. Functional success is not sufficient evidence that those surfaces are safe.

This baseline defines the minimum security/privacy evidence required before a commercial beta can pass a launch gate. It uses NIST Cybersecurity Framework 2.0 as the high-level lifecycle and OWASP ASVS 5.0 as the application-verification baseline. NIST AI RMF concepts apply to automated/AI-generated research components where model-risk governance is relevant. These are engineering references, **not** claims of certification, registration, or legal compliance.

## 1. Required security posture

### Govern

- Name an owner for security, privacy, incident response, identity/entitlements, secrets, delivery reliability, performance evidence, and model/research governance.
- Maintain a risk register with severity, owner, mitigation, evidence, and review date.
- Treat material architecture changes as security-review triggers.
- Require explicit launch evidence; missing evidence is a **NO-LAUNCH** state.

### Identify

Maintain a versioned inventory of:

- customer/account metadata;
- authentication/session data;
- entitlement and subscription state;
- billing-event metadata (never raw payment-card data unless separately approved and required);
- delivery/audit history;
- support/admin records;
- research outputs and archives;
- paper/backtest/performance evidence;
- API keys/secrets/service credentials;
- application, Lambda, queue, database, storage, email, identity and billing dependencies.

Every data class must declare: owner, sensitivity, source, permitted roles, retention/deletion rule, encryption requirement, log restrictions, backup class, and customer-impact level.

### Protect

- Server-side authorization is authoritative; client-side hiding is never an entitlement control.
- Unknown identity, tenant, subscription, billing, or entitlement state fails closed.
- Cross-tenant access is denied by default and covered by automated isolation tests.
- Privileged/admin access requires stronger authentication than ordinary subscriber access and supports prompt revocation.
- Prefer scoped service identities and short-lived credentials where supported; avoid shared long-lived privileged credentials.
- Secrets are environment-separated, centrally stored, auditable, rotatable, and never committed to the repository.
- Sensitive data is protected in transit and at rest; logs exclude secrets, raw tokens, payment data, and unnecessary customer content.
- Dependency/configuration changes are reviewed and reproducible.

### Detect

Security events must be observable without exposing sensitive payloads. At minimum capture:

- successful and failed authentication;
- failed authorization and tenant-isolation checks;
- privileged/admin actions;
- entitlement overrides and subscription-state changes;
- secret access/rotation events where the platform supports audit telemetry;
- repeated billing-event replay or signature failures;
- abnormal API/rate-limit behavior;
- suspicious report-delivery/replay activity;
- production/staging configuration drift;
- security-control failures and unexpected disabled controls.

Each event should carry timestamp, environment, actor/service identity, tenant/customer surrogate ID where appropriate, action, result, correlation ID, and source component. Do not place sensitive content in the event body.

### Respond

Define a provider-neutral incident process with:

1. detection and triage;
2. severity assignment;
3. containment/disable path;
4. credential/session/token revocation where relevant;
5. evidence preservation;
6. customer-impact assessment;
7. recovery/replay decision;
8. root-cause review and corrective actions.

The response plan must include account takeover, entitlement bypass, billing replay, tenant-data leakage, secret compromise, report tampering/spoofing, privileged-support abuse, and compromised dependency scenarios.

### Recover

- Backups are encrypted and access-controlled separately from primary workloads where practical.
- Restore permissions are limited and audited.
- Recovery procedures identify RPO/RTO targets by data class and align with #87.
- Restore drills must prove customer/account, audit-history, performance-evidence, and critical research-output recovery before launch.
- Recovery must not silently overwrite immutable historical evidence.

## 2. Threat model

The minimum threat model must cover the following abuse cases.

| Threat | Example | Required evidence |
|---|---|---|
| Account takeover | stolen session/token or credential stuffing | session controls, privileged MFA policy, revocation test, auth logging |
| Entitlement bypass | canceled/past-due user accesses premium outputs | server-side entitlement tests, fail-closed unknown state |
| Cross-tenant leakage | customer A reads customer B state/data | tenant-isolation unit/integration tests |
| Billing replay | duplicate/out-of-order event grants stale access | idempotency/replay tests tied to #85 |
| Secret compromise | API/token exposed or reused across environments | secret inventory, rotation procedure, access audit |
| Report spoof/tamper | customer receives wrong/stale/altered output | immutable manifest/hash/correlation evidence tied to #87 |
| Privileged-support abuse | manual override without authorization/audit | privileged role matrix and immutable admin audit |
| Dependency compromise | vulnerable package or third-party outage changes behavior | dependency inventory, scanning/review evidence, fail-closed behavior |
| Research/model drift | model/prompt/data change silently alters customer output | versioning/change-control evidence and model-governance gate |
| Data overcollection | unnecessary sensitive/customer data retained indefinitely | data-minimization and retention/deletion evidence |

## 3. Privacy-minimized data model

Default commercial-beta principle: collect the least customer information needed to authenticate, authorize, deliver the product, support the account, measure product health, and satisfy separately reviewed operational/legal requirements.

Before collecting a new field, document:

- product/operational purpose;
- whether the field is required or optional;
- sensitivity level;
- retention period;
- deletion/account-closure behavior;
- who can access it;
- whether it enters analytics/logging;
- whether an anonymized/aggregated surrogate can replace it.

Product analytics should prefer pseudonymous account IDs and aggregated event data. Never place credentials, secrets, payment-card data, brokerage credentials, or unnecessary portfolio details into analytics.

## 4. Secure development and verification

Before a beta release, maintain repeatable evidence for:

- dependency vulnerability review;
- secret scanning / repository-secret checks;
- code review for identity, entitlement, billing, privileged/admin, customer-data and delivery code paths;
- automated authorization/tenant-isolation tests;
- replay/idempotency tests;
- input validation and output encoding for customer-facing APIs/pages;
- security-event logging tests;
- rate-limit/abuse controls for high-cost endpoints;
- environment separation and configuration-drift review;
- backup/restore evidence;
- incident-tabletop evidence;
- threat-model review after material feature changes.

The target application baseline should use OWASP ASVS 5.0 controls as the verification catalog, with higher assurance applied to authentication, session management, authorization, data protection, security logging, API security, configuration, and cryptography.

## 5. AI / research-model governance hook

Automated research components may affect ranking, wording, explanations, or customer-visible conclusions. Before a material model/prompt/data-source change reaches customer output, record:

- model/prompt/schema/code version;
- input data cutoff and freshness rules;
- intended use and prohibited use;
- validation/ablation evidence;
- known limitations and failure modes;
- rollback version;
- approval/review status;
- whether the change invalidates prior performance evidence or customer-facing methodology claims.

This aligns with the continuous GOVERN / MAP / MEASURE / MANAGE lifecycle in NIST AI RMF without asserting regulatory status.

## 6. Beta security launch gate

A commercial beta is **NO-LAUNCH** unless all required items below have evidence references.

- [ ] Customer/data inventory is complete and versioned.
- [ ] Authentication/session design and privileged-access policy are documented and tested.
- [ ] Server-side entitlement enforcement and tenant-isolation tests pass.
- [ ] Billing replay/idempotency and fail-closed account-state tests pass.
- [ ] Secret inventory, environment separation, rotation and revocation procedures exist.
- [ ] Security-event logging covers authentication, authorization and privileged actions.
- [ ] Threat model is reviewed for the intended beta architecture.
- [ ] Dependency/security verification checklist passes for the release candidate.
- [ ] Backup/restore evidence and incident-response/tabletop evidence exist.
- [ ] Delivery integrity/reliability evidence from #87 passes.
- [ ] Performance/marketing evidence gate from #86 passes for any customer-facing claims.
- [ ] External legal/regulatory review gate from #97 is satisfied for the exact product scope.
- [ ] Live brokerage execution remains disabled for the research-subscription beta.

## 7. Evidence artifact format

Each release candidate should be able to produce a machine-readable or auditable record containing:

- release/version identifier;
- environment;
- evidence collection timestamp;
- control/check identifier;
- PASS / FAIL / NOT_APPLICABLE;
- evidence location/hash;
- owner;
- expiration/review date;
- unresolved exception and approved expiry, if any.

A missing required control is not interpreted as PASS.

## 8. Source anchors

Primary/high-quality engineering references:

- NIST Cybersecurity Framework 2.0: https://www.nist.gov/publications/nist-cybersecurity-framework-csf-20
- NIST CSF 2.0 resource center: https://www.nist.gov/cyberframework
- NIST AI Risk Management Framework: https://www.nist.gov/itl/ai-risk-management-framework
- OWASP Application Security Verification Standard: https://owasp.org/www-project-application-security-verification-standard/
- OWASP ASVS 5.0 security-event logging: https://cornucopia.owasp.org/taxonomy/asvs-5.0/16-security-logging-and-error-handling/03-security-events
- OWASP ASVS 5.0 data-protection documentation: https://cornucopia.owasp.org/taxonomy/asvs-5.0/14-data-protection/01-data-protection-documentation

## Explicit non-goals

This baseline does **not**:

- certify Daily Alpha against NIST, OWASP or any regulatory framework;
- decide legal/privacy/regulatory applicability;
- authorize production/customer deployment;
- authorize payment processing or collection of payment-card data;
- authorize personalized investment advice or live trading;
- replace external security, privacy, legal or compliance review where required.
