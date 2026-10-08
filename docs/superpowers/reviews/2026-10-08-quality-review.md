# Quality review (Opus), 2026-10-08: findings and approved fix list

Range: c359cd9..ed6c57c. Grade **B+**. No critical correctness bugs. The user approved the full fix list below on 2026-10-08.

## Speed (measured on 261 steps × ~4,020 rows per snapshot)
- **S1. Full-chain scans for quotes.** `find_quote` takes 83% of run time. It is a 4-predicate polars `filter` over ~4,000 rows, at 0.61 ms per call and ~29 calls per step. The callers are `mark()` (~2.4 runs per step, loop.py:96, 148, 264), the strategy exit check (rule_strategy.py:35) and `add_spread_cost`→`mid_prices`. A prototype per-chain dict index `(expiration, strike, right) → (bid, ask)` gave identical results and ran 3.7–7× faster (demo 4.76s→1.27s; daily-entry 12.68s→1.76s). Build the index lazily per step. Do not cache it in `QuoteStore`: that costs ~300 MB per underlying-year.
- **S2. Polars per-call overhead in as-of lookups.** `MarketData.asof` takes 0.24 ms per call and `History._tail` 0.61 ms. Keep sorted Python lists and use `bisect_right` (0.0007 ms). Files: market.py:36-42, history.py:23-24.
- **S3. Slow synthetic generation.** `generate_chains` takes 4.05s per 1M rows: Python `list.extend` of numpy scalars plus building a DataFrame from lists. Build one frame per date block from numpy arrays, `pl.concat` them, and use `scipy.special.ndtr` (synthetic.py:75-104).
- **S4. Wasted test time.** `test_cli.py:11` `demo_root` is function-scoped and imports the demo 3×; make it module-scoped via `tmp_path_factory`. `test_import_twice_needs_replace_flag` (:77) re-imports 1M rows twice; use a 1-row CSV. Saves about 15–20s of the ~60s suite.

## Duplication → helpers (src)
| Helper | Locations |
|---|---|
| `index_quotes(chain) -> dict[ContractKey, tuple[float, float]]` in data/chain.py, replacing `find_quote`. Make `ContractKey` a `NamedTuple`. `FillModel.prices(quotes, legs, opening)` and `mid_prices(quotes, legs)` share one `_quotes_for` loop. The engine passes `self.quotes.get(u, {})`, removing the "chain present else None" branches. | chain.py:15-22; fills.py:34-53; loop.py:125-126, 136-137, 181-182 (`fill_prices`), 190-191; portfolio.py:101-102; rule_strategy.py:32-37 |
| `_Run._close_at_market(position, ts, reason) -> bool` (prices → spread cost → fee → close → log) | loop.py:122-133, 188-195 |
| `ny_date(ts) -> date` and `ny_date_expr(col="ts") -> pl.Expr` in data/schema.py | market.py:40, loop.py:100 (twice), filters.py:95, rule_strategy.py:38, selectors.py:17, conftest.py:81; store.py:90, 130; periods.py:54-55 (`_et_date`, move it); test_loop.py:94; test_synthetic.py:179 |
| `load_yaml(path, kind=dict)` moved out of strategy/config.py (fixes data→strategy layering, O2) | config.py:147-157; periods.py:31-39 |
| `validate_model(model_cls, raw, source)` giving dotted `loc: msg` errors (tabular currently dumps raw pydantic text) | config.py:160-167; criteria.py:32-37; tabular.py:69-74 |
| `read_csv_or_raise(path, what, **kw)` plus a dated-series variant | market.py:14-22; filters.py:78-84; synthetic.py:109-112; tabular.py:77-81 |
| `_pick_floats(frame, source, raw_path, prefix)` combining `_pick` and `_floats` | tabular.py:95-104, 125-135, 139-152 |
| `_annualized_ratio(equity, risk)`; `_excess_returns` returns a Series; sortino becomes `excess.clip(upper_bound=0).pow(2).mean() ** 0.5` | metrics.py:66-93 |
| `operator.gt/ge/le` in place of the lambdas | criteria.py:61-85 |
| Compute `entry_net` once: `Portfolio.open(..., prices)` sets the entry prices itself | loop.py:142-144; portfolio.py:34 |

## Duplication (tests)
- **test_margin_sizing.py:** the first four tests should use the existing `_size` helper (:22-63).
- **test_tabular.py:** `_mapping(tmp_path, sample="long", **edits) -> Path` replaces 9 copies of the write-mapping-from-sample-with-`.replace()` pattern and `_wide_mapping_text` (:60, 77, 88, 96, 109, 116, 141, 148, 168-185). Delete `test_shipped_mappings_load` (:155), which `:238` covers.
- **helpers `daily_pcs(**overrides)`:** PCS with `schedule={}`, `max_open_positions=1` and 100k cash (conftest.py:121-126; test_loop.py:20-28; test_sweep.py:14-19).
- **helpers `weekdays(start, n)`** (conftest.py:39-44, 72-77; helpers.py:76-81).
- **test_metrics.py:** add an `EMPTY_TRADES` constant and `_metrics(equity, trades=EMPTY_TRADES, stats=None)` (:110, 131-210). Delete `test_max_drawdown` (:22), which `:26` covers.
- **test_portfolio.py:** add `_open_pcs(qty=1, commission=0.0)` and `CLOSE = time(15, 45)` (:22-27, 51-53, 63-65, 177-179, and the `settle_expired` calls).
- **test_config.py:** one `_set(raw, path, value)` walker (:14-20, 220-225, 242-247); merge the two `test_example_config_*` tests (:23-36).
- **Helper aliases:** drop `expiry_ts` (identical to `snapshot_ts`) and `TS`/`TS_DATE` (they duplicate `T0`) (helpers.py:46-47, 70-71; test_portfolio.py:119/139/152; test_selectors).
- **helpers `first_chain(root, underlying="SPY")`** (test_tabular.py:17-19, 25-26; test_store.py:115-116, 121-122).
- **test_store.py:** a `parquet_reads` fixture (:70-72, 81-83).
- **test_periods_criteria.py:** a `_statuses(*args, **kw)` helper (:115, 150, 163, 166, 240).
- **Minor:** `_strategy(**entry)` in test_rule_strategy.py (7 uses; :14 copies `_cfg`); an `events_file` fixture for test_filters.py:26, :47.

## Comments and docstrings
- **Stale:**
  - test_periods_criteria.py:42 says "Feb 1 (Thu) .. Feb 28 (Wed)", but the period is Feb 1–2.
  - test_metrics.py:39 says "1 day … 4 days", but the stretches are 2 and 6 calendar days.
- **Delete:** module docstrings that only restate the module name (cli.py:1, metrics.py:1, periods.py:1, helpers.py:1, and the others of that kind); the `# Review Focus 5` comment in test_schema.py:111.
- **Add one-line explanations:**
  - position.py:77-82: why spot 0 plus each strike is enough (the payoff is piecewise linear with kinks at the strikes, and net calls ≥ 0 make it non-decreasing above the top strike).
  - position.py:85-110: the greedy cover pairing gives a conservative bound.
  - sizing.py:8: why `+ 1e-9`.
  - store.py:126-127: the tie-breaks (earlier expiration, lower strike).
  - selectors.py:69: why `.round(9)`.

## Other quality issues
- **O1. Filter rejections are invisible.** rule_strategy.py:70-74 logs them only at DEBUG, so the zero-trade warning (loop.py:219-227) gives the wrong sizing advice. Fix: `ctx.stats.reject(f"filter:{type}")`, and show the sizing hint only when `size_zero` dominates.
- **O2. Layering.** `load_raw` lives in strategy/config.py but is imported by tabular.py:12 and criteria.py:10. Fixed by the `load_yaml` move above.
- **O3. Dead loggers.** `log`/`import logging` are unused in engine/position.py:1,9; data/adapters/synthetic.py:1,15; strategy/selectors.py:1,13; strategy/exits.py:1,7.
- **O4. Strategy legs are mutated.** loop.py:142-143 writes `entry_price` onto the strategy's `order.legs` before sizing. Pass `prices` to `Portfolio.open` and copy legs with `dataclasses.replace`.
- **Minor:**
  - `OpenOrder.reason` (base.py:18) is never read: log it in the "opened" line or drop it.
  - Type-hint gaps: loop.py:75, 181, 184; portfolio.py:112 (`MarginModel`); criteria.py:40; sweep.py:100; tabular.py:125.
  - Make `Portfolio.open`'s `commission`, `max_loss` and `tags` keyword-only.
  - exits.py:44: use an explicit `(field, reason, rule)` table.
  - criteria.py:58: `0.0 - max(losses)` should be `-max(losses)`.
  - store.py:91-95: Python mask → lazy `.filter(ny_date_expr() >= start)`.
  - metrics.py:13, 48-62: UTC `.date()` → `ny_date`.
  - loop.py:96: local `mark_value` shadows the method of the same name; store `strategy` on `_Run`.
  - Move `RunStats` out of strategy/base.py: it is an engine concept.
  - Tests in the wrong place: `write_quotes` tests in test_synthetic.py:84-155 → test_store; the `RunStats` test in test_config.py:164; the shipped-config test in test_cli.py:85. Local imports: test_synthetic.py:76, test_tabular.py:239, test_report.py:135, test_market.py:43.
  - Weak or duplicate tests: test_synthetic.py:87 (`rows_dropped >= 0`); test_schema.py:108 (`"1" in caplog.text`); test_position.py:96-112 and partly :80-93; test_report.py:31 (covered by :40); test_sweep.py:112 (covered by :118); test_schema.py:38/:43 → parametrize; the provenance tests (test_report.py:95, 103, 112, 159) build unneeded stores (`QuoteStore(tmp_path)` works).

## Approved fix list (≈ −60 lines src, ≈ −140 lines tests, 4–7× faster runs)
1. Quote index (S1): `ContractKey` NamedTuple, `index_quotes`, index-based `FillModel.prices` and `mid_prices`, `StepContext.quotes`, `_Run` builds `self.quotes` lazily per step; remove `fill_prices` and the None branches; update the `find_quote` tests.
2. Count filter rejections; make the zero-trade hint depend on the reason (O1).
3. Bisect-based `MarketData.asof` and `History` slices (S2).
4. `_close_at_market` in loop.py.
5. `ny_date` / `ny_date_expr`, replacing ~11 call sites.
6. New `options_bt/loaders.py` with `load_yaml`, `validate_model`, `read_csv_or_raise`, used by config, periods, criteria, tabular, market, filters and synthetic (O2).
7. tabular `_pick_floats`.
8. metrics `_annualized_ratio`; criteria `operator`.
9. `Portfolio.open(prices=...)`, no leg mutation, keyword-only args (O4).
10. Remove the 4 dead loggers; decide `OpenOrder.reason`; fill the type-hint gaps; remaining src minors above.
11. Vectorize `generate_chains` (S3).
12. Test helpers and cleanup (all items in "Duplication (tests)"), including moving misplaced tests and deleting duplicate or weak tests.
13. Module-scoped `demo_root` and a tiny CSV for the import-twice test (S4).
14. Comments: fix the 2 stale ones, delete the restating docstrings, add the 5 one-liners.
