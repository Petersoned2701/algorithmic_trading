# Options Backtest Engine — Design Spec

**Date:** 2026-10-07
**Status:** Draft, awaiting review
**Background research:** `reports/Options swing trading research 2026.md`

## 1. Purpose and scope

### Intended outcome
A reusable, test-driven Python backtesting engine for multi-leg US options strategies. Its first job is to answer one question: **does the core strategy (laddered 30–45 DTE put credit spreads on SPY/XSP) have an edge after realistic costs?** It must do so before any money is spent on data subscriptions or any broker is chosen.

### What the user stated
- Long-term goal: swing-trade options, moving from backtest to paper trading to live trading.
- Account under $25k. Defined-risk strategies only to start; both constraints may loosen later.
- This sub-project covers the data pipeline and the backtest engine.
- Development and tests run in Claude Code cloud sessions on small synthetic data. Full backtests run on the user's own machine.
- Usage: a library at the core, a thin CLI with YAML configs, and notebooks for exploring results.
- Accepted go/no-go criteria (Section 8).
- Engineering practices: TDD, logging, specific error handling, readable and maintainable code. When in doubt, write less code.
- The engine must handle a variety of strategies, including higher-risk ones, so it can be reused.
- Time frames must be extensible to day trading later. Day trading is not built in this effort.

### Assumptions (open to correction)
- Daily near-close snapshots are enough for swing holding periods.
- Initial data comes from a free SPY/QQQ/IWM EOD dataset. An ORATS Near-EOD purchase may follow.
- A single process on one machine is enough; no distributed execution.

### In scope
Canonical data format and converters, Parquet storage, the step loop, a declarative rule-based strategy, a fill/cost model, settlement at expiration, position sizing and portfolio caps, metrics and reports, parameter sweeps, and the CLI.

### Out of scope (the design leaves room for each)
- Broker connections, paper trading and live trading
- Intraday data and day-trading rules
- Rolling or adjusting positions
- Margin for undefined-risk positions
- Physical share assignment and early exercise of American-style options

## 2. Tooling
- Python 3.12, managed with `uv`; `src/` layout; package name `options_bt`.
- Runtime dependencies: `polars`, `pyarrow`, `pydantic` (v2), `pyyaml`, `matplotlib`, `scipy`. scipy supplies the normal CDF for Black-Scholes in synthetic data.
- Development dependencies: `pytest`, `ruff`.
- The CLI uses stdlib `argparse`, to keep the dependency list short.

## 3. Architecture

```
src/options_bt/
  errors.py            # DataError, ConfigError, NoContractFound
  logging_setup.py     # console (INFO) + per-run file handler (DEBUG)
  data/
    schema.py          # canonical quote schema + validation
    store.py           # Parquet store: list timestamps, load chain at ts
    market.py          # auxiliary daily series: T-bill rate, VIX, VIX3M
    adapters/
      synthetic.py     # Black-Scholes chain generator (tests + demo)
      tabular.py       # mapping-driven CSV/Parquet importer (free dataset, ORATS, ...)
  strategy/
    base.py            # Strategy protocol, StepContext, Order
    config.py          # pydantic models for strategy YAML
    selectors.py       # leg selection (dte + delta / strike offset)
    filters.py         # registry: vix_term_structure, iv_rank, event_blackout
    exits.py           # registry: profit_target, stop_loss, dte_exit
    rule_strategy.py   # RuleStrategy built from config
  engine/
    position.py        # Leg, Position (max loss, mark, cost to close)
    portfolio.py       # cash, open/closed positions, equity
    loop.py            # the step loop
  execution/
    fills.py           # fraction-of-spread fill model
    costs.py           # commissions
    settlement.py      # settlement at expiration
  risk/
    sizing.py          # max-loss sizing + portfolio caps
    margin.py          # MarginModel protocol; DefinedRiskMargin
  analytics/
    metrics.py         # return, Sharpe, Sortino, drawdown, trade stats
    periods.py         # stress-period and in/out-of-sample splits
    criteria.py        # pass/fail evaluation against criteria.yaml
    report.py          # report.md + charts
  sweep.py             # expand parameter grid, run, compare
  cli.py               # options-bt run | sweep | data import
configs/               # strategy YAMLs, criteria.yaml, stress_periods.yaml, events.csv
  mappings/            # one column-mapping YAML per data source (dubach.yaml, orats.yaml)
examples/              # small committed price paths + market CSVs for the synthetic demo
tests/                 # mirrors src/; fixtures/ holds small synthetic Parquet
```

Each module has one job and can be tested on its own. The engine depends on the `Strategy`, `MarginModel` and fill-model interfaces, never on concrete strategies.

## 4. Data

### Canonical quote schema (one row per contract per snapshot)
| Column | Type | Notes |
|---|---|---|
| `ts` | datetime (UTC, µs) | Snapshot time. Daily data has one `ts` per trading day (e.g. 15:45 ET). |
| `underlying` | str | e.g. `SPY` |
| `underlying_price` | f64 | Price at `ts` |
| `expiration` | date | |
| `strike` | f64 | |
| `right` | str | `C` or `P` |
| `style` | str | `american` or `european` |
| `settlement` | str | `physical` or `cash` |
| `bid`, `ask` | f64 | NBBO at `ts` |
| `delta` | f64 | Required. Taken from the vendor (or computed by the synthetic generator). Sources without greeks are rejected with a `DataError`; an IV solver is deferred. |
| `iv` | f64, nullable | Taken from the vendor when present |
| `multiplier` | i32 | Default 100 |

The date is derived from `ts` and never stored separately.

### Validation (`schema.validate`)
- Required columns and types must be present; otherwise raise `DataError`.
- Rows with `bid > ask`, negative prices, or `ask <= 0` are dropped and counted, with a WARNING log.

### Storage
Parquet files are partitioned as `data_root/quotes/underlying=<U>/year=<Y>/*.parquet`. `store.py` uses polars lazy scans and offers:
- `timestamps(underlyings, start, end) -> list[datetime]`
- `chain(underlying, ts) -> pl.DataFrame`

A missing chain for a timestamp the store lists raises `DataError`. Market holidays never appear because they have no rows.

### Auxiliary series
`market.py` loads small daily files from `data_root/market/`: T-bill rate (FRED DTB3), VIX and VIX3M. Lookups are as of `ts` (the last value at or before it), so they never look ahead.

### Converters
Each converter is a function `convert(raw_path, data_root) -> ImportSummary`. It maps the source's columns to the canonical schema, validates, and writes the partitions.
- `synthetic` generates chains from a given underlying price path, constant IV and a bid-ask width rule. It drives tests and the demo.
- `tabular` is one importer driven by a mapping YAML (`configs/mappings/<source>.yaml`) that renames columns, maps call/put values, sets defaults (style, settlement, multiplier, snapshot time), and handles both long (one row per contract) and wide (call and put columns on one row) layouts. Adding a source means adding a mapping file, not code. The `dubach` and `orats` mappings are written from documentation and are marked unverified until checked against a real sample file.

## 5. Engine

### Core types
- **`Leg`:** contract key (underlying, expiration, strike, right), signed quantity per unit, entry price.
- **`Position`:** id, legs, quantity (units), entry ts, entry net price, commissions paid, and `tags` (e.g. which strategy opened it). Derived values:
  - `max_loss()`:
    - **Single-expiry positions:** worst-case payoff over all underlying prices at expiry, computed from the leg payoffs at the strike breakpoints and at the extremes (0 and ∞), minus the net premium.
    - **Multi-expiry positions** (calendars, diagonals): every short leg must be covered by a long leg of the same right and quantity that expires no earlier. The max loss is then the net debit plus any adverse strike gap between each short leg and its cover (zero for a calendar).
    - It is `None` when the loss is unbounded or a short leg is uncovered.
  - `mark(chain)` at the midpoint.
  - `close_price(chain, fill_model)`.
- **`Order`:** open (legs + quantity request) or close (position id), plus a reason string.
- **`Portfolio`:** cash, open positions, closed-trade records, last-known marks per leg (for stale-mark carry-forward), and `equity(ts)`.

### Step loop (`loop.run(config, store, strategy, ...) -> RunResult`)
For each `ts` in `store.timestamps(...)`:
1. **Load** the chain for each underlying, plus the as-of market values.
2. **Settle** every leg with `expiration < ts.date()`, and every leg with `expiration == ts.date()` when `ts` is at or after the session close (a configurable time, default 15:45 ET for daily data). Settlement pays intrinsic value against `underlying_price` from the settlement snapshot. Physical-settlement legs are cash-settled at intrinsic value and logged as `assignment`.
3. **Mark** open positions at the midpoint. A missing leg quote carries the last mark forward and increments `stale_marks`.
4. **Call the strategy:** `strategy.on_step(ctx)` returns orders.
5. **Process closes first.** Each close fills via the fill model. A close with a missing quote is deferred to the next step, with a WARNING log.
6. **Process opens.** For each open: `risk.size()` computes the quantity (0 means rejected, with the reason logged); the fill model prices it; commissions are deducted; the position is added.
7. **Record** equity, cash, open-position count and total max-loss exposure.

Settlement runs before the strategy so that it never sees expired legs. Because the loop only ever iterates over timestamps the store provides, intraday bars need no loop changes.

### Fill and cost model
- A fill for a multi-leg order of n legs uses `fill_fraction[n]` (default `{1: .75, 2: .66, 3: .56, 4: .53}`). For each leg, buys pay `bid + f × (ask − bid)` and sells receive `ask − f × (ask − bid)`. So f = 0.5 means the midpoint and f = 1.0 means crossing the full spread. The same rule applies to opening and closing, so every round trip pays the spread twice.
- Commission is `commission_per_contract × contracts × legs`, plus optional per-order fees.
- A config field `fill_fraction_override` supports "mid-fill upper bound" runs (all 0.5) and stress runs (e.g. 0.9).

### Sizing and caps (`risk/`)
- `MarginModel.requirement(position) -> float | None`. `DefinedRiskMargin` returns `max_loss`. If that is `None` (unbounded risk), the open is rejected, logged at WARNING ("defined_risk margin model does not allow undefined-risk positions") and counted in the run's skipped-entry stats. A later `RegTMargin` would return a number instead.
- `size()`: `quantity = floor(max_loss_pct_equity × equity / requirement_per_unit)`. The result is then reduced until `total_requirement ≤ max_total_max_loss_pct × equity` and `requirement ≤ cash`.

## 6. Strategies

### Interface
```python
class Strategy(Protocol):
    def on_step(self, ctx: StepContext) -> list[Order]: ...
```
`StepContext` holds:
- `ts`
- `chains: dict[str, pl.DataFrame]`
- `positions` (read-only views)
- `equity`
- `market` (as-of lookups)
- `history`: read-only access to earlier snapshots and underlying prices, for indicators such as IV rank

`ctx` exposes nothing dated after `ts`.

### `RuleStrategy` (YAML-configured)
The config is validated by pydantic models; any validation failure raises `ConfigError` with the field path. Top-level fields:
- `name`, `underlyings`
- `entry.schedule`: weekdays and/or every-N-steps
- `entry.max_open_positions`
- `entry.filters`: a list of `{type, ...params}`
- `entry.legs`: a list of leg selectors. Each selector has `right`, `side`, `ratio` (default 1), and either:
  - (`dte: [min, max]`, `delta`), which picks the expiration in range closest to the midpoint of the range, then the strike with the closest |delta|; or
  - (`ref`, `strike_offset`), which uses the same expiration as the referenced leg unless `dte` is given, then strike = reference strike + offset, snapping to the nearest listed strike within a tolerance.
- `exits`: `profit_target_pct`, `stop_loss_multiple`, `dte_exit`. Each is optional; expiration always applies.
  - Profit and loss are measured relative to the entry credit (or the debit, for debit structures).
  - DTE is measured in calendar days to the position's earliest expiration.
- `sizing`, `portfolio_caps`, `costs`, `margin_model` (default `defined_risk`)
- `account`: `initial_cash` (default 15,000), `cash_interest` (default false; when true, cash accrues the T-bill rate daily), `session_close` (default 15:45 ET)

Exit conditions are evaluated on the **fill-model close price**, not the midpoint.

If any leg cannot be selected, a `NoContractFound` is raised inside the strategy. It is caught there and logged at DEBUG, and that underlying's entry is skipped for the step.

### Registries
Filters and exits are plain functions registered in a dict by `type` name. Adding one means writing a function, registering it, and adding a test.

Initial filters:
- `vix_term_structure(max_ratio)`: VIX/VIX3M as of `ts`.
- `iv_rank(min, max, lookback_days)`: computed from the trailing ATM IV of the 30-DTE-nearest expiry, using history up to and including `ts` only.
- `event_blackout(file, days_before, days_after)`: dates come from `configs/events.csv`.

## 7. Sweeps
Any scalar field in a strategy config may instead be `{sweep: [v1, v2, ...]}`. (A plain list can't be the marker, because fields such as `dte` and `underlyings` are already lists.) `sweep.py` expands the Cartesian product, runs each combination sequentially (a parallel option is deferred), and writes `sweep_results.parquet/.csv` with one row per combination of parameters and key metrics. It also computes a **neighbour robustness score**: the share of combinations within one grid step of the best combination that are profitable.

## 8. Analytics and go/no-go criteria
- **Metrics** (`metrics.json`):
  - Annualized return using calendar time, and excess return over the T-bill rate.
  - Sharpe and Sortino ratios, using daily equity returns minus the daily T-bill rate, annualized by √252 for daily data. The periods-per-year factor is derived from the timestamp spacing.
  - Max drawdown and its duration.
  - Number of trades, win rate, average win and average loss, profit factor, worst trade.
  - Total commissions and total spread cost (fill versus midpoint), and costs as a percentage of gross P&L.
  - Data-quality counts: dropped quotes, stale marks, deferred closes, skipped entries.
- **Periods:**
  - `configs/stress_periods.yaml` defines 2008-09–2009-03, 2018-02, 2020-02–2020-04, 2022, 2024-08 and 2025-04. Return and max drawdown are reported for each period.
  - When `oos_start` is set, metrics are computed separately for in-sample and out-of-sample.
- **Criteria** (`configs/criteria.yaml`, checked on every run):

| Check | Default |
|---|---|
| Net return | > 0 |
| Annualized return vs T-bills | Excess return > 0 |
| Max drawdown | ≤ 25% |
| Worst stress-period loss | ≤ 15% of equity |
| Out-of-sample net return | > 0 (only when `oos_start` is set) |
| Neighbour robustness (sweeps only) | ≥ 60% |

Each check reports PASS/FAIL/N-A with the actual value.

## 9. Outputs
Each run writes to `runs/<UTC timestamp>_<name>/` (git-ignored):
- `config.yaml`: resolved config plus git commit, data root and data fingerprint (file count and total size per partition)
- `trades.parquet` and `trades.csv`
- `equity.parquet`
- `metrics.json`
- `report.md`
- `equity_drawdown.png`
- `run.log`

## 10. Errors and logging
- **`errors.py`:** `BacktestError` (base) → `DataError`, `ConfigError`, `NoContractFound`.
  - The CLI catches `BacktestError` subclasses, prints a one-line message, and exits non-zero.
  - Any other exception is a bug: it propagates with a traceback.
- **Logging:** stdlib `logging`, with `logging.getLogger(__name__)` per module.
  - `logging_setup.configure(run_dir, verbose)` attaches a console handler (INFO, or DEBUG with `-v`) and a `run.log` file handler (DEBUG).
  - INFO: run start and end, one line per opened or closed trade, sweep progress.
  - DEBUG: per-step decisions.
  - WARNING: data-quality events.

## 11. CLI
```
options-bt run <strategy.yaml> --data-root PATH [--start DATE --end DATE] [--oos-start DATE] [-v]
options-bt sweep <strategy.yaml> --data-root PATH [...]
options-bt data import synthetic <price_path.csv> --data-root PATH
options-bt data import tabular <raw_path> --mapping configs/mappings/<source>.yaml --data-root PATH
```

## 12. Testing
- **TDD throughout:** every behaviour starts as a failing test.
- **Synthetic fixtures:** tests build synthetic Parquet stores in a temporary directory from small price paths (flat, steady rise, crash through the short strike), so nothing large is committed. `examples/` holds a committed price-path CSV and market CSVs so the demo runs in a cloud session without downloads.
- **Unit tests for:**
  - Schema validation
  - Store lookups
  - As-of market lookups (including no look-ahead)
  - Each leg selector
  - The fill formula
  - Commissions
  - `max_loss` for verticals, iron condors, butterflies, calendars, diagonals, and unbounded cases (naked put or call returns `None`)
  - Settlement (cash and physical)
  - Sizing and caps
  - Each filter and exit
  - Each metric against hand-computed values
  - Criteria evaluation
  - Config validation errors
- **End-to-end tests:**
  - A flat path makes a put credit spread expire worthless; P&L equals credit minus costs.
  - A crash path makes the loss equal max loss plus costs.
  - The profit target triggers on the expected step.
  - A sweep produces the expected number of rows.
- **Quality bar:** `uv run pytest` and `uv run ruff check . && uv run ruff format --check .` must pass before every commit. The suite should run in under about 30 seconds.

## 13. Extension points (not built now)
| Future need | Where it plugs in |
|---|---|
| Intraday / day trading | New adapter producing many `ts` per day; a session-close setting; a time-of-day exit rule; a pattern-day-trader / intraday margin rule in `risk/` |
| Undefined-risk strategies | A new `MarginModel` (e.g. `RegTMargin`) selected by `margin_model` |
| Early assignment / share delivery | Replace the settlement function; add a stock position type |
| Rolling and adjustments | A custom `Strategy`, or new order types handled in the loop |
| Paper and live trading | Reuse `Strategy`, selectors, filters and sizing; swap the loop's data source and fill model for a broker adapter |
