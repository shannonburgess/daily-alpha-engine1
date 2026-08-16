# Pine SQS Processor Boundary

The Pine ingress queue is an authenticated, sanitized event source. The processor is the next safety boundary before any paper-ledger mutation.

## Current processor behavior

The processor:

- accepts only ingress schema `2026-08-16-v2` from `TRADINGVIEW_PINE`
- requires `trading_authorized=false`, `paper_execution_triggered=false`, and `live_trading_enabled=false`
- rejects any queued payload containing `webhook_secret`
- accepts only canonical strategy `DA_TURTLE_ADAPTIVE_TREND` version `1.9` on daily timeframe (`D` or `1D`)
- enforces `ADD_1_ATR` / `ADD_2_ATR` at `position_fraction=0.25`
- enforces `HARVEST_3_ATR` for `PARTIAL` at `position_fraction=0.25`
- rejects stale queue events
- persists accepted events idempotently by `signal_id` into the staging DynamoDB table
- marks accepted events `HELD_FOR_CONTEXT`
- never opens, adds to, partially closes, or exits a paper position
- never enables live brokerage execution

## Why events are held

A Pine price is the **underlying stock price**. It is not a valid option fill price. Therefore an option `ADD`, `PARTIAL`, or `EXIT` cannot be booked from a Pine webhook alone.

`ENTRY_LONG` also cannot safely create a paper position from the webhook alone because the engine still requires current portfolio/risk state and current ORATS contract-quality/pricing context.

The hold reasons are explicit:

- `ENTRY_REQUIRES_PORTFOLIO_RISK_ORATS_CONTEXT`
- `ADD_REQUIRES_OPEN_POSITION_AND_INSTRUMENT_FILL_CONTEXT`
- `PARTIAL_REQUIRES_OPEN_POSITION_AND_INSTRUMENT_FILL_CONTEXT`
- `EXIT_REQUIRES_OPEN_POSITION_AND_INSTRUMENT_EXIT_PRICE_CONTEXT`

## AWS wiring

Do **not** enable the SQS event-source mapping until the processor Lambda, least-privilege IAM role, DynamoDB write permission, and DLQ behavior have been created and functionally tested. Existing manual ingress test messages should be removed from the queue before enabling consumption.

The next implementation layer will resolve held events against current paper position state, portfolio/risk context, and current instrument pricing before calling the paper runtime.
