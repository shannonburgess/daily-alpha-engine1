# Decisions Log — daily-alpha-engine1

This file tracks decisions, incidents, and standing rules for AI tools (Claude, ChatGPT)
working on this repo, so nothing gets duplicated, contradicted, or silently lost across
tools or sessions.

## How to use this file
- Before starting a session with either AI, paste the most recent entries below so it has context.
- After a session, add a new entry summarizing what was proposed, what was accepted/rejected, and why.
- Every AI-proposed change must go through a pull request (enforced by the `main` branch ruleset) — nothing merges without review.
- For stacked/dependent PRs: always verify the merge target is `main` specifically, not just that the PR shows "Merged" — see incident below.

## Role assignments (current)
- **Claude**: code review, bug-spotting in strategy logic (lookahead bias, data leakage, overfitting risk), reviewing PRs before merge.
- **ChatGPT**: first-draft generation of new backtest scripts / workflow scaffolding, opens PRs only — no direct merges.
- **Human (Shannon)**: final approver on all PRs to `main`. No AI merges automatically.

## ChatGPT's confirmed operating commitment (2026-08-26)
- Refines open PRs, fixes failing checks, addresses review notes.
- Will NOT push or merge anything to `main`.
- PRs remain Draft or Ready for review.
- Shannon gives final approval; Claude does independent review.
- Morning/end-of-day handoffs include: PRs touched, changes made, test/check results,
  unresolved review notes, dependency order, execution/risk/CIO/portfolio impact.
- PRs touching execution, risk, portfolio authority, or infrastructure/AWS receive
  heightened review and cannot progress without explicit approval.
- If anything comes up mid-task that seems more urgent, ChatGPT stops and asks before
  switching — does not decide unilaterally, even if planning to disclose later.
- Progress must come with an artifact (a real file/matrix), not a description. No
  artifact = no progress claim, even "in progress" needs a partial file behind it.
- New parameters require out-of-sample validation before paper-shadow use.
- One parameterized backtest workflow replaces ticker-specific workflows.

## Open questions / standing rules
- No new "Analyze [ticker] thresholds" one-off workflows — consolidate into a single parameterized backtest workflow instead.
- Any new strategy parameter set must pass out-of-sample validation (a time window not used for tuning) before being added to a paper-trading shadow workflow.
- Self-patching workflows (e.g. `apply-next-session-code-fixes.yml`, `fix-execution-universe-lint.yml`) must open PRs, not push to `main` directly.
- Business direction: platform (Daily Alpha / Convex Ridge) first. Hedge fund and VC arms are a later-stage consideration, not simultaneous — conflict-of-interest and dual-registration complexity must be solved with real securities counsel before that stage begins.
- PRs are only added to the "restructuring register" when evidence supports it (oversized, mixed-purpose, or genuinely tangled dependencies) — not merely because a PR is large.

## Pre-launch checklist — marketing site claims vs. actual system
The Convex Ridge marketing site (convex-ridge.shannon-burges677435.chatgpt.site) makes
specific numeric/factual claims about Daily Alpha that must be verified against the real
system before the site goes live to anyone external:
- [ ] "36 independent data source agents" — trace to an actual named list; confirm current
      count of implemented adapters (as of 2026-08-26: adapters for OVTLYR, sector,
      liquidity, Pine are live on `main` via #270-#272) vs. planned total.
- [ ] "1M+ evidence points evaluated" — confirm whether this is a real measured figure from
      the evidence store or an aspirational/target number. If real, document how it's
      calculated and from what date range.
- [ ] "6 independent discovery engines" — confirm these map to real, implemented components,
      not planned architecture from docs.
- [ ] Five solution tiers (Investor, Investor Pro, Advisor, Institutional, Enterprise) —
      confirm which tiers are actually orderable/functional at launch vs. aspirational.
- [ ] Social media content — do not launch regular posting until claims above are verified;
      same standard as the website applies to any public content.
Rule going forward: any specific number or claim added to the public site or social content
must trace back to a real, verifiable system component — same verification standard applied to PRs.

## Log

### 2026-08-26 — Incident — Stacked PR merge targets caused a false "complete" status
**Context:** Morning review (this doc's earlier session) confirmed #270, #271, #272 as
merged, based on GitHub showing "Merged" and Shannon confirming via screenshots.
**What actually happened:** #271 merged into `feat/agentic-intelligence-v1-foundation`
(a feature branch, #270's branch) — not into `main`. #272 merged into
`feat/agentic-intelligence-v1-existing-adapters` (#271's branch) — also not `main`.
Only #270 itself had actually reached `main` directly.
**How it was found:** ChatGPT's Batch 4 PR classification pass (dependency mapping for
#274/#275) discovered #274 and #275 depend on #271/#272 ancestry "not present on main"
and flagged both as Blocked. Verified independently via GitHub file browser (adapters.py
and durable_evidence.py were absent from `main`) and by checking each PR's actual
"merged X commits into ___ from ___" line.
**Fix:** Opened #398 (main ← feat/agentic-intelligence-v1-foundation, carrying #271's
commits) and #399 (main ← feat/agentic-intelligence-v1-durable-evidence, carrying #272's
commits). Both reviewed as already-approved content, checks passed, merged into `main`
directly. Confirmed via file browser: `adapters.py` and `durable_evidence.py` now present
on `main`.
**Lesson:** For stacked PR chains, "Merged" alone does not confirm content reached `main`.
Always check the specific merge target. A PR merged into a parent feature branch does not
carry forward automatically if that parent branch is merged to `main` *before* the child
PR lands on it.
**Status:** Resolved. #274/#275 should be re-evaluated now that their blocking ancestry is
in place.

### 2026-08-26 — Process incident — Silent priority reordering (AM)
ChatGPT deviated from the agreed 67-PR triage task without disclosure, prioritizing
new implementation (PR #396/#397, reconciliation work) instead. Root cause
(self-identified): execution/communication failure — not a technical blocker.
The reordering itself wasn't disclosed until asked directly.
**Corrective action:** standing rule added — no silent priority changes. Must check in
before switching tasks, not just disclose after the fact.

### 2026-08-26 — Process incident — Estimated work reported as in-progress without execution (PM)
Midday classification estimate (5-7 hours) was given, but no classification work was
actually performed afterward — no PR-by-PR review, partial matrix, or saved artifact.
Not a case of starting and hitting a blocker; work was described as underway when it
was not. No technical blocker existed.
**Corrective action:** Task broken into verifiable batches of 10-15 PRs. Progress only
reported from a saved artifact (real matrix file) after each batch — no artifact, no
progress claim.

### 2026-08-26 — PR classification progress
Batches 1-4 complete (40 of 69 classified) using verifiable methodology: `git cherry`
for commit uniqueness, `git merge-tree` for clean trial merges, explicit scoping of what
triage does/doesn't prove (not final code approval, targeted tests not rerun).
- Keep: 27, Superseded: 1, Blocked: 8, Needs review: 4
- Restructuring register: #127 (split into 5 branches, prepared), #193, #206, #221, #265
- Key dependency chains mapped: commercial launch evidence (#160→#164→#169→#172),
  manual watchlist stack (#199→#206, blocked), MU intraday chain (#256→#258→#259→#262→
  #263→#265, all blocked pending #256), Security Master chain (#274→#275, was blocked
  on the stacked-PR gap above, now resolved).
- Accepted roadmap: Investor / Investor Pro first. Advisor, Institutional, Hedge Fund
  Suite, and Enterprise deferred or gated. (#101 marked Superseded on this basis.)

---

<!-- Add new entries above this line, most recent first -->
