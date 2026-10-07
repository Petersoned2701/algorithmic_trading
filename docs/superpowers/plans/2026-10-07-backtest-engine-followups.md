# Backtest engine — follow-ups deliberately left for later

Non-blocking items found in per-task and final reviews and left unchanged for now (final review triage: "leave").

## Worth doing before trusting real-data results
- **Collateral check (M2):** `size()` compares a new position's requirement with cash, which includes credits already received. A broker holds `width × 100` per spread, so with `max_total_max_loss_pct` near 100 the book can be slightly over-committed. Keep the cap well below 100 (the example uses 15).
- **Strict prior-close VIX option (M3):** the regime filter sees the same-day VIX/VIX3M close at the 15:45 snapshot, about 30 minutes early. A `<`-only as-of option would be the conservative choice.
- **Vendor mappings:** `configs/mappings/dubach.yaml` and `orats.yaml` use unconfirmed column-name guesses (`verified: false`). Check them against a real sample before importing.
- **Market CSV hygiene:** null, NaN or duplicate dates in `market/*.csv` are not rejected.

## Extensibility (when adding new strategy types)
- `run()` builds `RuleStrategy` and requires a `StrategyConfig`. A minimal `RunConfig` (account, costs, margin, sizing, caps) would decouple custom strategies.
- `MarginModel.requirement(legs, net_premium)` has no spot or marks. A Reg-T margin model will need a signature change.
- `StepContext.positions` and `.chains` are mutable, although the spec says read-only.

## Polish
- Relative paths: `event_blackout`'s default file and the `--criteria`/`--stress` defaults are relative to the working directory.
- CLI `run`/`sweep` leaves an orphan run directory when a data error occurs. CLI `sweep` duplicates `sweep._scalar` and expands the grid twice.
- An out-of-sample window with fewer than 2 equity rows reports `net_return` 0.0, which shows as FAIL rather than N/A.
- `write_quotes(replace=True)` deletes the old files before writing the new ones, so a failed write leaves the partition empty. Re-importing recovers it.
- Assignment labelling is lost when a calendar's front leg is assigned and the back leg closes later.
- Small test gaps: ratio-spread `max_loss` cases, `iv_rank` through a real `History` with 252+ varied-IV days, and the ET-vs-UTC boundary branches.
