# Quality review 3 (Opus), 2026-10-08: after the second fix wave

Range: c359cd9..a8d058f. Grade **A**. No critical bugs. **Status: awaiting the user's decision. Nothing has been dispatched.**

## Previous fix list
Items 1–9 landed. Item 10 was skipped on purpose; the reviewer agrees.

**Speed:** output is bit-identical. Demo run 1.60s → ~0.96s; daily-entry run 2.25s → ~1.42s. The test suite takes 9.6s.

**Size:** src +5 lines, tests −30 lines. src is now 2,720 lines and tests 3,262.

## Proposed fix list
1. **S1:** use an eager boolean mask in `_select_leg` (selectors.py:31). Net 0 lines. Daily-entry run −18%.
2. **Sweep-config errors name the file:** add `run_sweep(..., source)` and have the CLI pass `config <path>`. Parametrize the CLI config-error test over `run` and `sweep`. About +3 lines.
3. **test_loop config builders:** use `parse_config(daily_pcs(...))` and `{**PCS_NO_FILTERS, ...}` instead of `model_dump`/`deepcopy` round trips. −6 lines.
4. **Test tidies:** drop the `(LONG_CSV)` parentheses; merge the two long-layout tabular tests; add a `_load_vix` helper in test_market. About −7 lines.
5. **(Optional; trades code for speed) S2:** a vectorised `Quotes` index class that searchsorts over int64 contract codes instead of a per-snapshot dict.
   - Index build: 2.3–2.9 ms → 0.26 ms.
   - Demo: 0.97s → 0.49s (0.40s with S1). Daily-entry: 1.44s → 0.82s (0.68s with S1). Output identical.
   - About +20 src lines. Strikes are resolved to 1/1000. One test changes (test_store.py:118-125 switches to `.get`).
   - Saves about 9s per 4,300-step underlying-run, multiplied by sweep size; more with intraday data.

Items 1–4: about +3 src lines and −13 test lines.

## Dismissed
- Caching the quote index in the store: 316 MB per underlying-year.
- Garbage-collector tuning.
- Caching `requirement`: it needs invalidation after partial settlement.
- Nested `_set` calls in test_config.
- A `spy_quotes` fixture.
