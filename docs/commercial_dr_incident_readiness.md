# Daily Alpha Commercial DR & Incident Readiness

Status: **internal planning / staging only**  
Tracks: #81, #87, #103  
This document defines testable internal recovery and incident-readiness hypotheses. It does **not** create a public SLA, deploy production, contact customers, or authorize live trading.

## 1. Objective

A paid research product must recover not only application availability but also the integrity of customer access, immutable research history, performance evidence and delivery audit trails.

The recovery model therefore separates:

- customer/account state;
- entitlement/subscription state;
- billing-event evidence;
- research source/history inputs;
- ranked research outputs;
- customer-visible report/archive outputs;
- performance/audit evidence;
- delivery observations;
- security/operational logs;
- configuration and secrets.

A successful restore must not silently rewrite historical research or convert missing evidence into a healthy state.

## 2. Recovery classes

The values below are **initial internal hypotheses to validate in staging**, not customer commitments.

| Class | Examples | Initial RPO hypothesis | Initial RTO hypothesis | Recovery rule |
|---|---|---:|---:|---|
| A — access control | customer identity mapping, entitlement state, required acknowledgements | <= 15 min | <= 2 hr | fail closed if state is uncertain |
| B — billing evidence | normalized provider events, idempotency/replay keys, account-state transitions | near-zero where durable event replay exists; otherwise <= 15 min | <= 4 hr | never grant access from an unverified reconstructed event |
| C — immutable research history | dated OVTLYR inputs, signal versions, ranked outputs, model manifests | <= 24 hr | <= 8 hr | restore immutable dated objects; never overwrite prior history |
| D — customer reports/archive | dated HTML/PDF/CSV bundles, report manifests | <= 24 hr | <= 4 hr | regenerate only from versioned source/manifests and mark regenerated artifacts |
| E — performance/audit evidence | paper ledger, actual-fill evidence, backtest manifests, claim registry evidence | <= 24 hr | <= 8 hr | preserve evidence class and lineage; missing evidence remains missing |
| F — delivery audit | scheduled/delivered/source-as-of/correlation observations | <= 15 min | <= 4 hr | no inferred delivery success without observation evidence |
| G — config/secrets | environment config, secret references, runtime flags | reproducible config + secret recovery procedure | <= 2 hr | no secret values in Git/backups intended for source control |

Each class must eventually have a concrete storage implementation, backup mechanism, retention policy, restore command/runbook and test artifact.

## 3. Backup policy requirements

### Immutable history

- preserve dated research/source/report history as immutable objects where practical;
- enable versioning or an equivalent protection against accidental overwrite/deletion;
- keep a stable `latest` pointer/bundle separate from immutable dated history;
- a restore of `latest` must be derived from a verified immutable version, not treated as the source of truth.

### Databases / ledgers

- use point-in-time recovery or versioned export where the backing service supports it;
- preserve idempotency keys, correlation IDs and event timestamps;
- verify restored customer/account/entitlement rows against billing-event evidence before reopening access;
- preserve audit chronology rather than compacting away failed/denied transitions needed for investigation.

### Secrets and configuration

- back up configuration declarations and secret identifiers, not plaintext secret values in the repository;
- document re-issuance/rotation paths for credentials that cannot or should not be restored;
- a disaster-recovery event that may expose credentials triggers rotation before service is reopened where appropriate;
- production and staging credentials remain separate.

## 4. Restore validation

A backup is not considered valid until a restore drill proves the recovered system can answer the expected integrity questions.

### Customer/access restore checks

- can the system identify active vs inactive entitlement state correctly?
- are canceled/past-due/unknown accounts still denied?
- do required acknowledgement/version records survive?
- can a replayed billing event be processed idempotently without duplicate entitlement mutation?
- is cross-tenant access still denied after restore?

### Research-history restore checks

- do immutable date/version identifiers match pre-restore manifests?
- do content hashes/manifests match where available?
- are prior research outputs preserved rather than regenerated under a newer strategy version?
- can a specific historical recommendation be traced to the input/model version that produced it?

### Performance-evidence restore checks

- ACTUAL, PAPER, BACKTEST and HYPOTHETICAL classes remain separate;
- no missing trade/ledger evidence is silently reconstructed as a confirmed fill;
- performance report inputs can be traced to restored immutable records;
- claim-registry evidence remains linked to the correct period/version.

### Delivery restore checks

- delivered vs missed vs late vs stale events remain distinguishable;
- customer-impact correlation IDs survive;
- replay cannot create duplicate customer delivery without an explicit idempotent reason;
- a report with unavailable/stale source data cannot be restored as a normal successful delivery.

## 5. Staging restore-drill matrix

Before beta, run at least these scenarios in a non-production environment:

1. accidental deletion of a `latest` report bundle;
2. accidental deletion/corruption of one dated research output;
3. loss of the customer entitlement datastore snapshot;
4. billing-event replay after datastore recovery;
5. loss of delivery-observation records;
6. application rollback while customer/account data remains newer;
7. secret revocation/rotation during recovery;
8. simulated corrupted research output requiring publication disable;
9. simulated dependency outage during scheduled report generation;
10. restore from backup into an isolated validation environment before cutover.

For each drill record:

- scenario ID;
- start/end time;
- data class;
- backup version/time;
- measured recovery point;
- measured recovery time;
- integrity checks;
- missing/corrupt records;
- customer-impact simulation;
- corrective actions;
- PASS / FAIL;
- evidence link/hash.

## 6. Incident severity model

This is an internal triage model, not a public response-time commitment.

### SEV-1 — integrity/security/widespread critical failure

Examples:

- wrong customer/tenant receives protected data;
- entitlement bypass or suspected account/secret compromise;
- materially incorrect/corrupted research output delivered broadly;
- widespread critical report delivery uses stale data while appearing valid;
- evidence/history corruption that could make performance claims unreliable;
- widespread billing/account-state mutation with uncertain correctness.

Default response posture:

- stop/disable the affected customer-facing path;
- preserve evidence;
- revoke/rotate credentials or sessions when indicated;
- fail closed on uncertain access/data state;
- identify blast radius before normal operation resumes;
- require explicit recovery verification.

### SEV-2 — major availability or partial customer-impact failure

Examples:

- missed/late critical report for a material customer cohort;
- partial authentication/entitlement outage with correct fail-closed behavior;
- archive unavailable while current report delivery remains healthy;
- significant third-party data/provider outage blocking normal publication.

Default response posture:

- contain/retry safely;
- identify affected cohorts;
- use idempotent replay where validated;
- do not publish a normal-looking report when required data is stale/unavailable.

### SEV-3 — limited/customer-specific operational failure

Examples:

- individual delivery failure;
- isolated account/support issue;
- non-critical analytics or archive metadata discrepancy.

Default response posture:

- ticket/audit the issue;
- correct through controlled support/admin path;
- escalate if pattern/blast radius grows.

### SEV-4 — no current customer impact

Examples:

- non-production bug;
- monitoring warning below customer-impact threshold;
- documentation/configuration drift found before deployment.

Default response posture: schedule corrective work and verify no hidden customer impact.

## 7. Incident lifecycle

Every material incident follows the same evidence-driven sequence:

1. **Detect** — alert, audit anomaly, support report or dependency signal.
2. **Triage** — classify severity and affected systems/data/customers.
3. **Contain** — disable delivery/access path where integrity is uncertain.
4. **Preserve** — protect logs, manifests, event records and relevant versions.
5. **Diagnose** — establish source, blast radius and earliest affected timestamp.
6. **Recover** — restore/replay only through tested/idempotent procedures.
7. **Verify** — run integrity and entitlement/research/delivery checks.
8. **Reopen** — restore customer path only after required checks pass.
9. **Review** — root cause, contributing controls, corrective actions and evidence.
10. **Learn** — update tests/runbooks/monitoring and challenger assumptions where relevant.

## 8. Publication kill/disable control

Commercial research delivery needs a control independent from trading execution that can stop new customer-visible publication when:

- required source data is stale/unavailable;
- report render/readability QC fails;
- output-manifest integrity fails;
- delivery duplication/replay safety is uncertain;
- entitlement isolation is uncertain;
- a security incident requires containment.

Requirements:

- default state and current state are auditable;
- disable does not delete already published immutable history;
- re-enable requires evidence checks appropriate to the triggering condition;
- publication disable cannot enable or modify live trading;
- customer-facing status language, if later used, must be reviewed and factual.

## 9. Dependency-outage behavior

For each critical external/internal dependency define:

- owner;
- health signal;
- timeout/retry policy;
- stale-data limit;
- fallback allowed / not allowed;
- effect on report publication;
- effect on customer access;
- queued/replay behavior;
- maximum safe catch-up batch;
- incident severity trigger.

High-priority dependencies include:

- ORATS / options data;
- OVTLYR/source-history intake;
- public market/macro/catalyst sources;
- storage/database/queue/compute;
- email/report delivery;
- identity;
- billing/payment-event provider;
- DNS/web/API edge when those surfaces exist.

An alternate data route is not automatically a valid fallback. Compatibility and freshness must be explicitly verified.

## 10. Incident communication readiness

Before customers are onboarded, prepare internally reviewed templates for:

- service disruption acknowledgement;
- missed/late research delivery;
- stale/invalid output withdrawal;
- account/access interruption;
- security/privacy event notification workflow, subject to external legal review;
- resolution / service restored;
- post-incident summary where appropriate.

Templates must never speculate about root cause or impact before evidence exists and must not promise a public SLA that has not been approved.

## 11. Postmortem requirements

SEV-1 and material SEV-2 incidents require an internal postmortem containing:

- timeline;
- impact/blast radius;
- detection source and detection delay;
- root cause;
- contributing factors;
- what worked / failed in containment and recovery;
- data integrity result;
- customer-impact result;
- corrective actions with owner/date;
- new/updated tests;
- monitoring/runbook changes;
- whether product claims/performance evidence need re-review;
- whether external notification/review requirements apply.

Avoid blame-oriented language; focus on controls, evidence and remediation.

## 12. Commercial beta reliability launch gate

The reliability/DR portion of commercial beta is **NO-LAUNCH** unless:

- [ ] PR #100 delivery-SLO/readiness evidence passes on real staging observations.
- [ ] Critical data classes have actual storage mappings and backup mechanisms.
- [ ] Restore drills demonstrate measured RPO/RTO against internally approved targets.
- [ ] Identity/entitlement restore preserves fail-closed behavior.
- [ ] Billing replay is idempotent after restore.
- [ ] Immutable research/performance history survives restore without silent rewriting.
- [ ] Publication kill/disable path is tested.
- [ ] Dependency outage/freshness behavior is documented and tested for critical sources.
- [ ] SEV classification, ownership and escalation paths are assigned.
- [ ] At least one end-to-end incident tabletop has evidence and corrective actions.
- [ ] Security/privacy controls from #103 are incorporated.
- [ ] No public SLA is marketed without evidence and approval.
- [ ] Live trading remains outside the commercial research-beta recovery path.

## 13. Definition of done for this planning layer

This specification is complete when it has been translated into provider-specific staging runbooks/tests with real measured restore evidence. The document alone is not reliability proof.
