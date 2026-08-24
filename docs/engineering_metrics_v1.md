# Engineering Metrics V1

Daily Alpha records a deterministic engineering-footprint snapshot in CI so line-count and build-efficiency claims can be tied to exact repository evidence instead of retrospective estimates.

## Measurement boundary

The collector reads only files returned by `git ls-files` at the exact checked-out commit. Supported UTF-8 text files are grouped into source, tests, infrastructure/CI, scripts, TradingView, configuration, documentation, and other text.

The headline `developed_nonblank_lines` total includes:

- source;
- tests;
- infrastructure and CI;
- scripts;
- TradingView;
- configuration.

Documentation is reported separately and is not included in the developed-line headline. Raw `data/` content, virtual environments, Git/cache directories, unsupported binary formats, and generated/base64 payloads are excluded.

## Line semantics

`physical_lines` is the count returned by Python `text.splitlines()`.

`nonblank_lines` counts physical lines that contain at least one non-whitespace character. This is intentionally a reproducible physical-footprint metric, not a claim that each nonblank line is executable code or has equal economic value.

The report includes exact per-file metrics, category/language aggregates, the Git commit SHA, and a deterministic SHA-256 `report_id` derived from those facts.

## Local use

After installing the package:

```bash
daily-alpha-engineering-metrics --format json
daily-alpha-engineering-metrics --format markdown
```

The normal test workflow also runs the Markdown form after Ruff and pytest and appends it to the GitHub Actions job summary. That makes every qualifying CI run an exact repository-linked measurement point.

## Publication and economics use

These metrics are suitable as evidence for longitudinal engineering analysis, including:

- source/test/infrastructure footprint growth;
- test-to-source footprint ratios;
- architecture and operational-control growth;
- exact commit-linked snapshots for future case-study tables;
- reconciliation of management LOC estimates against reproducible repository counts.

They must not be presented as audited financial savings or as a direct measure of quality, developer productivity, investment performance, or enterprise value. Engineering-hour and cost-equivalent claims require separate documented methodology and direct cost/hour evidence.

## Safety boundary

This instrumentation is descriptive only. It has no model, portfolio, broker, PAPER, AWS-deployment, TradingView-mutation, capital, execution, or live-trading authority.

`trading_authorized=false`

`live_trading_enabled=false`
