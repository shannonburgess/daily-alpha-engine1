# Prospect / Subscriber Opportunity Board V1

## Status

This is an **initial-rollout launch requirement**, not a post-launch roadmap item.

The first ConvexRidge / Daily Alpha prospect and subscriber experience is not ready unless it can present the three highest-ranked current qualifying opportunities prominently while also making the complete qualifying set available from the same canonical snapshot.

## Product rule

**Rank, do not ration.**

The canonical discovery set has no arbitrary presentation cap. If 50 names qualify, all 50 remain available. The first three receive deeper executive treatment as the **Top 3 ConvexRidge Picks** and ranks 4 through 50 remain valid, ranked qualifying opportunities.

If fewer than three names qualify, the system presents only the names that actually qualify. It must never weaken evidence, liquidity, data-quality, model or risk standards merely to fill three slots.

## Upstream full-universe contract

The canonical staging source is the stock-primary `shortlist.json` written from every item in `ResearchShortlistResult.items`. The stock-primary builder evaluates every actionable row that survives its actual company/ETF eligibility, point-in-time data-quality, liquidity and price gates.

The `request_limit` argument is **only an ORATS research-enrichment quota**. The current staging workflow sets it to 20, but candidates beyond the first 20 are retained with `RESEARCH_API_LIMIT_STOCK_RETAINED`; they are not deleted from stock discovery and their stock score is not changed by ORATS availability or option quality. The shortlist writer enumerates every retained item and writes every row to `shortlist.json`.

The V1 regression suite explicitly constructs 50 valid candidates with `request_limit=20` and requires all of the following simultaneously:

- exactly 20 optional ORATS research requests;
- all 50 candidates retained in the stock-primary result;
- all 50 written to `shortlist.json` with ranks 1 through 50;
- all 50 passed into the same prospect board/API as Top 3 plus 47 additional opportunities.

This prevents an enrichment quota from accidentally becoming a customer-facing discovery cap.

## Canonical structure

`ProspectOpportunityBoard` is built from the existing ranked `CandidateAssessment` stream.

- `top_picks`: ranks 1 through at most 3.
- `additional_opportunities`: every qualifying opportunity after rank 3.
- `opportunities`: the complete canonical qualifying set.
- `filtered`: non-qualifying candidates with explicit reason lineage rather than silent deletion.
- paginated pages: bounded views over the complete canonical set; pagination never changes `total_qualifying`.
- filtered pages: deterministic query views over that same immutable set; filtering never rewrites discovery membership or rank.

The same candidate cannot exist simultaneously in the qualifying and filtered sets. Duplicate symbols fail closed.

## Pagination and filtering

V1 filtering is a presentation/query capability, not a second qualification engine. `OpportunityBoardFilter` supports deterministic exact-match filtering by:

- symbol;
- lifecycle status;
- qualifying bucket;
- sector;
- theme/industry context;
- preferred/selected instrument expression.

Filter inputs are normalized and bound to a deterministic `filter_id`. Non-qualifying buckets such as `DATA_ERROR` cannot be smuggled into a qualified-board query.

Every page retains:

- the immutable canonical `board_id`;
- `total_qualifying`, which always counts the entire qualifying discovery set before filters;
- `total_matched`, which counts the current query result;
- original canonical ranks rather than re-ranking a filtered subset;
- the deterministic `filter_id`, offset, limit and `has_more` state.

The API projection uses this page contract directly. A user can therefore filter or paginate a 50-name board without turning the canonical 50 into a smaller hidden universe. Clearing the query returns the same complete canonical set.

## Qualification, ranking and retained context

V1 preserves the existing candidate ranking semantics rather than inventing a second ranking engine:

1. qualified option setup;
2. qualified stock fallback;
3. entry watch;
4. data error;
5. no trade.

Only the first three buckets enter the qualifying prospect board. Data errors and no-trade candidates remain visible in the filtered audit set. Within the canonical ranking, the existing candidate score and deterministic symbol tie-break are preserved.

Lifecycle information such as NEW BUY, EMERGING, LEADER, ENTRY WATCH and RE-ENTRY is preserved from the source candidate assessment. DETERIORATING and REMOVED rows remain auditable as filtered/not-currently-qualified when present in the source snapshot.

The V1 opportunity contract also retains available context rather than reducing a candidate to ticker + rank. Fields include score and optional confidence, source classification reason as the current research thesis, exact evidence lineage, sector, industry/theme, trend, momentum, price, 30-day average volume, derived average daily dollar volume, preferred research expression, option research details, catalyst/risk context and invalidation when supplied by the source. Empty context remains empty; the prospect layer does not manufacture evidence or an invalidation rule that does not exist upstream.

Every opportunity carries evidence lineage to the exact canonical source revision. In staging this source revision is the SHA-256 identity of the exact `shortlist.json` bytes used to construct the board.

## Discovery is not portfolio recommendation

The prospect board represents governed research/model signals. It does not authorize a personalized portfolio recommendation, PAPER mutation, execution or live trading.

A later portfolio/risk layer may decide that a qualifying opportunity should not be allocated to a particular account. That account-specific decision must not erase the opportunity from the broader discovery history or prospect/subscriber opportunity board.

The V1 contract therefore hard-codes:

- `portfolio_recommendation_authorized=false`
- `paper_mutation_authorized=false`
- `trading_authorized=false`
- `live_trading_enabled=false`

## Point-in-time identity

Every candidate receives a deterministic ID bound to:

- the opportunity snapshot `as_of` timestamp;
- the exact source revision;
- the normalized candidate assessment, including retained context.

The board ID is then derived from the exact ordered qualifying candidate IDs, filtered candidate IDs, source revision and as-of boundary. This provides reproducible point-in-time customer/prospect presentation lineage without creating a second investment-decision engine.

## V1 launch acceptance

Initial rollout is not ready unless all of the following are true:

1. Top 3 are displayed prominently when at least three opportunities qualify.
2. The complete canonical qualifying set is still available.
3. If 50 qualify, ranks 1 through 50 remain accessible and only presentation depth differs.
4. Fewer than three qualifying names results in fewer than three picks, not weaker standards.
5. Pagination/filtering cannot silently truncate or mutate the canonical set; filtered views retain canonical `board_id`, rank and full `total_qualifying` lineage.
6. An ORATS/API enrichment quota cannot truncate the canonical stock discovery set.
7. Available thesis, evidence lineage, theme/industry, liquidity, catalyst/risk context and invalidation survive into prospect/API outputs without invention.
8. Non-qualifying candidates retain explicit filter/rejection lineage.
9. The prospect board cannot create portfolio, PAPER, execution or live-trading authority.
10. Newsletter, dashboard and API consumers must consume this same canonical board rather than independently applying a Top-N truncation.

Tracks issue #337.
