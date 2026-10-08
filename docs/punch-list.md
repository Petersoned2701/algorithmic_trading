# Punch list

Items we've decided to come back to later. When a review or discussion turns up something to address later, add it here with where it came from. When an item is done or dropped, move it to **Closed** with the commit or the reason.

## Open

### Speed
- **Vectorised quote index (S2).** *From quality review 3, 2026-10-08.*
  - **Change:** replace the per-snapshot dict built by `index_quotes` (data/chain.py) with a small `Quotes` class. It would hold sorted int64 contract codes, `(expiration_days*2 + is_put)*1e10 + round(strike*1000)`, looked up with `searchsorted`.
  - **Measured gain:**
    - Index build: 2.3–2.9 ms → 0.26 ms per snapshot.
    - Demo run: 0.97s → 0.49s. Daily-entry run: 1.44s → 0.82s. Output identical.
    - Saves about 9s per 4,300-step underlying-run, multiplied by the number of sweep combinations; more with intraday data.
  - **Cost:** about +20 source lines. Strikes are resolved to 1/1000. `Quotes` becomes a class instead of a dict alias. test_store.py's index test would switch to `.get`.
  - **Prototype:** in the session scratchpad (`opus3/proto`), not kept.
  - **Revisit:** when real-data sweeps or intraday data make speed matter.
- **Sweeps re-read parquet for every combination.** Each year costs about 0.12s per underlying-year per combination. *From quality review 1.*

### Before trusting real-data results
- **Collateral check.** `size()` compares a new position's requirement with cash, and cash includes credits already received. A broker holds `width × 100` per spread, so with `max_total_max_loss_pct` near 100 the book can be slightly over-committed. Keep the cap well below 100 (the example uses 15). *From the correctness final review.*
- **Strict prior-close VIX option.** The regime filter sees the same-day VIX/VIX3M close at the 15:45 snapshot, up to about 30 minutes early. A `<`-only as-of option would be the conservative choice. *From the correctness final review.*
- **Vendor mappings unverified.** `configs/mappings/dubach.yaml` and `orats.yaml` use unconfirmed column-name guesses (`verified: false`). Check them against a real sample before importing.
- **Market CSV hygiene.** Null, NaN or duplicate dates in `market/*.csv` are not rejected.

### Extensibility (when adding new strategy types or intraday)
- **Decouple `run()` from `RuleStrategy`.** `run()` builds a `RuleStrategy` and requires a `StrategyConfig`. A minimal `RunConfig` (account, costs, margin, sizing, caps) would let custom strategies run without a rule config.
- **Margin model needs more inputs.** `MarginModel.requirement(legs, net_premium)` has no spot or marks, so a Reg-T margin model will need a signature change.
- **Read-only context.** `StepContext.positions` and `.chains` are mutable, although the spec says read-only.
- **Per-step loading in `_Run.step(ts)`.** Have it load its own inputs (chains, quotes, tbill, days since the previous step). Skipped in fix wave 2 because it added code; revisit for intraday. *From quality review 2, item 10.*

### Polish
- **Paths relative to the working directory:** `event_blackout`'s default file and the `--criteria`/`--stress` defaults.
- **CLI tidy-ups.** `run`/`sweep` leaves an orphan run directory when a data error occurs. CLI `sweep` duplicates `sweep._scalar` and expands the grid twice.
- **Short out-of-sample windows.** A window with fewer than 2 equity rows reports `net_return` 0.0, which shows as FAIL rather than N/A.
- **`write_quotes(replace=True)` ordering.** It deletes the old files before writing the new ones, so a failed write leaves the partition empty. Re-importing recovers it.
- **Assignment labelling.** It is lost when a calendar's front leg is assigned and the back leg closes later.
- **Small test gaps:** ratio-spread `max_loss` cases, `iv_rank` through a real `History` with 252+ varied-IV days, and the ET-vs-UTC boundary branches.

## Closed
