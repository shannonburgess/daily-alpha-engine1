# Issue #327 venture/private-market extension

ConvexRidge Ventures is now an explicit future consumer of the same asset-neutral intelligence
contracts described by issue #327.

Additional requirements captured by the implementation:

- `market_domain` separates PUBLIC from PRIVATE opportunities without inventing a second asset
  taxonomy.
- venture opportunities may use private-company equity, SAFE, convertible-note, private-credit,
  fund-interest, or other financing structures.
- investment-vehicle context carries business-line, vehicle, mandate, conflict-policy, and
  information-barrier identity without granting capital or execution authority.
- private-market financing terms remain optional and point-in-time.
- explicit conflict disclosures cover venture holdings, board roles, advisory relationships,
  commercial relationships, and public holdings.
- `MNPI_RESTRICTED` information cannot be marked as permitted for public-market research.
- one public/private opportunity graph can connect listed assets and private companies under the
  same structural thesis.
- Daily Alpha SH24/SH25 validation and stock-primary PAPER execution remain unchanged.

The purpose is architectural reuse: public-market products and a future venture fund should share
one evidence/thesis/opportunity vocabulary while keeping separate legal, mandate, conflict,
valuation, portfolio, risk, and execution authority.
