# Commercial Research Correction / Supersession / Retraction Protocol

Status: commercial-beta control-plane draft. No customer communication or production activation is performed by this document or its companion module.

## Purpose
Daily Alpha research artifacts are immutable for auditability, but customer-visible research must also support explicit correction when a source, model, methodology, performance basis, or material interpretation is later found invalid. The original artifact remains preserved; correction is represented by new status evidence and, when applicable, a new replacement report identity.

## States
- `VALID` — current artifact eligible for archive/current-view and evidence use.
- `UNDER_REVIEW` — impact is unresolved; block performance evidence reuse and delivery replay until resolved.
- `SUPERSEDED` — a newer artifact replaces the original for current-view purposes.
- `CORRECTED` — a corrected replacement report exists; the original remains immutable/non-current.
- `RETRACTED` — artifact must not be treated as current or replayed.

## Required event evidence
Every transition should retain:
- unique event ID;
- report ID and prior status;
- target status;
- reason code;
- timezone-aware event timestamp;
- replacement report ID when superseded/corrected;
- affected source/evidence/methodology IDs;
- affected delivery correlation IDs;
- actor/service identity in the future persisted implementation.

## Reason classes
Examples:
- `SOURCE_DATA_CORRECTED`
- `SOURCE_FRESHNESS_MISCLASSIFIED`
- `MODEL_OR_CODE_DEFECT`
- `METHODOLOGY_VERSION_MISMATCH`
- `PERFORMANCE_EVIDENCE_INVALIDATED`
- `MATERIAL_RENDERING_OR_LABEL_ERROR`
- `DELIVERY_OR_ENTITLEMENT_DEFECT`
- `EXTERNAL_REVIEW_HOLD`

Normal market movement after publication is not a correction event.

## Fail-closed behavior
- `UNDER_REVIEW`, `SUPERSEDED`, `CORRECTED`, and `RETRACTED` artifacts are not eligible for performance evidence reuse or automated delivery replay.
- A terminal/non-current artifact cannot be silently restored to `VALID`.
- Duplicate event replay is idempotent only when the projected state exactly matches the event; conflicting reuse of an event ID is rejected.
- A corrected/superseded report requires a distinct replacement report ID.
- Original report/evidence bytes and hashes remain unchanged.

## Integration boundaries
Future integration should connect this state to:
- report provenance (#116 / PR #150);
- performance methodology/claim evidence (#113 / PR #140);
- delivery and recipient suppression (#163/#164);
- DR/restore (#87/#111);
- customer support/complaint workflow;
- commercial launch evidence (#171/#172).

No integration may mutate trading authorization, the paper ledger, TradingView alerts, or live execution.

## Staging acceptance matrix
1. valid report -> under review blocks evidence/replay;
2. valid report -> corrected requires new report ID and leaves original immutable;
3. duplicate correction event is idempotent;
4. conflicting duplicate event ID fails closed;
5. retracted report cannot return to valid;
6. superseded report cannot return to under-review/valid state;
7. restore of persisted state cannot make a retracted/superseded report current;
8. delivery replay rejects any non-VALID artifact;
9. claim/performance registry invalidates evidence tied to non-current artifacts until a new valid report/evidence chain exists.

## External-review boundary
This control provides engineering/audit behavior only. Customer notification timing/content, retention periods, complaint obligations, and launch-specific legal/compliance requirements remain external-review questions and must not be inferred from this module.
