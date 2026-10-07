# options-bt

An options strategy backtesting engine. It replays option-chain snapshots, applies a YAML-defined rule strategy with a spread-aware fill model, margin and costs, and writes a run folder with trades, equity, metrics, a report and a go/no-go table. Parameter sweeps score how robust the best setting is.

## Setup

```bash
uv sync
uv run pytest -q
```

## Demo (synthetic data)

Generate Black-Scholes chains from a seeded SPY price path, add the market series, and run the demo strategy:

```bash
uv run options-bt data import synthetic examples/spy_path.csv --data-root data/demo
cp -r examples/market data/demo/market
uv run options-bt run configs/demo_pcs_synthetic.yaml --data-root data/demo --oos-start 2024-09-01
```

The run prints the run folder (under `runs/`) and the go/no-go table. The folder holds `report.md`, `metrics.json`, `trades.csv/.parquet`, `equity.parquet`, `equity_drawdown.png`, `config.yaml` (resolved config plus git commit and data fingerprint) and `run.log`.

`configs/pcs_spy_45dte.yaml` is the same put credit spread with an `iv_rank` filter, for real data. Synthetic IV is constant, so that filter never passes on synthetic chains; the demo config omits it. Synthetic results only show that the machinery works; they say nothing about a strategy.

Other commands:

```bash
uv run options-bt sweep CONFIG --data-root PATH       # fields written {sweep: [a, b, c]} become axes
uv run options-bt run CONFIG --data-root PATH --start 2024-03-01 --end 2024-09-30 -v
```

`--criteria` and `--stress` default to `configs/criteria.yaml` and `configs/stress_periods.yaml`, resolved from the current directory. Exit code is 0 on success and 2 on a configuration or data error (`error: ...` on stderr).

## Data layout

```
<data-root>/quotes/underlying=SPY/year=2024/part-0.parquet   # written by the importers
<data-root>/market/{vix,vix3m,tbill}.csv                     # columns: date,value
```

Market CSVs use `date,value` columns (ISO dates, values in the series' own units, e.g. percent). A raw FRED download such as DTB3 has `DATE,DTB3` columns with `.` for missing days and must be converted first:

```bash
uv run python -c "import polars as pl; pl.read_csv('DTB3.csv', null_values='.').rename({'DATE': 'date', 'DTB3': 'value'}).drop_nulls().write_csv('tbill.csv')"
```

## Known limitations

- Daily VIX and VIX3M closes are used as of the 15:45 ET snapshot, so the regime filter sees the close about 15 minutes early (a small look-ahead).
- Synthetic data has flat implied vol and no skew; it is for plumbing checks only.

## Extending

- **Add a data source:** write `configs/mappings/<source>.yaml` (column renames, call/put value mapping, defaults for style, settlement, multiplier and snapshot time; long or wide layout), then run `options-bt data import tabular RAW --mapping configs/mappings/<source>.yaml --data-root PATH`. No code changes.
- **Add a filter:** write `fn(ctx, underlying, **params) -> bool` in `src/options_bt/strategy/filters.py`, decorate it with `@register("name")`, add a test, and use `{type: name, ...params}` under `entry.filters`. Parameters are validated against the function signature.
- **Add an exit rule:** add the optional field to `ExitConfig` in `strategy/config.py`, write `rule(inputs: ExitInputs, value) -> bool` in `strategy/exits.py`, register it in `EXITS` under the same name, and add a test. Rules are checked in `EXITS` order.
