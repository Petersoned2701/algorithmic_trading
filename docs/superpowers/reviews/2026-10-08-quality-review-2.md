# Quality review 2 (Opus), 2026-10-08: after the fix wave

Range: c359cd9..2e02080. Grade **A−**. No critical bugs. **Status: awaiting the user's decision. Nothing has been dispatched.**

## Previous fix list
12 of 14 items landed fully. Items 5 (`ny_date`) and 6 (`loaders.py`) have small leftovers.

**Speed and test runtime:** `run()` went from 5.03s to ~1.7s on the demo (CLI 8.1s → 3.3s), and synthetic import from 12.9s to 2.0s. The output is bit-identical: 103 trades, final equity 46222.07. The test suite runs in 15s.

**Size:** the wave did not shrink the code as projected. src grew by 42 lines, mostly from the new `loaders.py`, `engine/stats.py` and the rejection counting. tests grew by 30 lines, with 8 more tests.

## Proposed fix list
1. **Plain-tuple keys in `index_quotes`** (chain.py:17-23). `ContractKey._make` is called 1M times, and `index_quotes` is about half of `run()`. Net 0 lines; demo −25%.
2. **List-based `_pick_by_delta` / `_pick_by_offset`** (selectors.py:60-87). `select_legs` takes 3.8 ms per entry; the list version takes about 0.2 ms. Daily-entry run −30%. Output identical in the prototype.
3. **Shorter CLI sweep test:** add `--end 2024-03-31` at test_cli.py:46. About −2.5s of suite time.
4. **One `read_table`:** `loaders.read_table(path, what, fmt)` replaces the single-caller `read_csv_or_raise` and tabular `_read`. −4 lines.
5. **Remaining `ny_date` call sites:** rule_strategy.py:49, store.py:98, conftest.py:78, test_loop.py:86, test_synthetic.py:88/:137.
6. **Config errors name the file:** `parse_config(raw, source)`, so CLI config errors show which file failed. Add a test.
7. **`_Run.equity()`** replaces `mark_value` arithmetic at 3 sites.
8. **Test cleanup** (about −50 lines):
   - a `flat_market` helper; a test_loop `_run` helper; merge same-scenario loop tests (3 fewer engine runs);
   - `LONG_CSV`/`LONG_MAPPING` constants and `_wide_csv` in test_tabular; drop `_mapping`'s dead default;
   - more `_set` uses in test_config; parametrize the provenance git-failure tests;
   - replace the strike-list literal; use `busday_count` in conftest;
   - delete the tautology at test_schema.py:42; stop mutating `MarketData.series` in test_filters.py:211.
9. **Source polish:** rename tabular `Mapping` → `ColumnMapping`; name `t_live` once in `_bs`; use `Sequence` hints in `Portfolio.close`/`_finish`; add a one-line `exit_value` comment.
10. **(Optional)** `_Run.step(ts)` loads its own per-step inputs (loop.py:243-264).

Expected overall: about −5 lines of src, −50 lines of tests, 1.6–1.8× faster engine runs, and about 16% off the test suite.

## Dismissed deferred minors
- **loop.py `net` for margin:** margin needs the net before sizing.
- **History making two store calls:** merging them ties History to the cache layout.
- **test `_set` using `setdefault`:** it's needed for `account.*` paths, and `extra="forbid"` still catches typos.
