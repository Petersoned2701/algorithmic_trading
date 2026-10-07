# Options Backtest Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A test-driven Python library and CLI that backtests YAML-defined multi-leg options strategies on timestamped option-chain snapshots, with realistic fills, sizing, settlement, metrics and go/no-go checks.

**Architecture:** An event-driven step loop iterates over the snapshot timestamps a Parquet store provides. Each step it settles expirations, marks positions, asks a `Strategy` for orders, and applies them through a fill model, a margin model and a sizer. Strategies are mostly declarative (`RuleStrategy` from YAML, with filter and exit registries). Analytics are computed from the trade log and the equity curve.

**Tech Stack:** Python ≥3.12, uv, polars, pyarrow, pydantic v2, pyyaml, scipy, matplotlib, pytest, ruff.

**Spec:** `docs/superpowers/specs/2026-10-07-backtest-engine-design.md`

## Global Constraints

- Package `options_bt` in `src/options_bt/`, managed with `uv`. `requires-python = ">=3.12"`.
- Runtime dependencies are limited to polars, pyarrow, pydantic (v2), pyyaml, scipy and matplotlib. Dev dependencies: pytest, ruff. The CLI uses `argparse`.
- **TDD:** every behaviour starts as a failing test.
- **Quality gate before every commit:** `uv run pytest -q`, `uv run ruff check .` and `uv run ruff format --check .` all pass.
- **Errors:** only `DataError`, `ConfigError` and `NoContractFound` (all subclasses of `BacktestError`) are raised deliberately. Other exceptions are bugs and propagate.
- **Logging:** each module uses `log = logging.getLogger(__name__)`. No `print` outside `cli.py`.
- **Timestamps:** tz-aware UTC `datetime`. Calendar logic (weekday, session close, DTE) is done in `America/New_York`.
- **Prices:** prices in quotes are per share. Position values, P&L, cash and margin are in dollars (× `multiplier`, default 100).
- **Sign convention:**
  - `Leg.qty` is positive for long, negative for short, per unit of position.
  - `leg_value(legs, prices) = Σ qty × price × multiplier`.
  - `entry_net = −leg_value(entry prices)`, so a credit is positive.
  - P&L per unit = `entry_net + leg_value(exit prices) + realized settlements`.
- **Defaults from the spec:**
  - `fill_fraction = {1: 0.75, 2: 0.66, 3: 0.56, 4: 0.53}`, `commission_per_contract = 0.65`
  - `initial_cash = 15000`, `session_close = 15:45 ET`, `margin_model = defined_risk`
  - Criteria: `max_drawdown ≤ 0.25`, worst stress loss `≤ 0.15`, `robustness ≥ 0.60`
- **Comments:** keep them sparse. Docstrings go only on public functions whose behaviour isn't obvious from the name and signature.

## Review Focus

1. **Expiring leg with no quote on expiration day** (strike delisted or missing). Settlement must use `underlying_price` and never need the leg's quote. Pinned in Task 8.
2. **Expiration on a market holiday** (e.g. Good Friday). The leg settles on the next available snapshot, because `expiration < ts.date()`. Pinned in Task 8.
3. **Data ends with positions open.** The final step force-closes them at fill-model prices with reason `end_of_data`, so trades and metrics are complete. If quotes are missing, it falls back to settlement at intrinsic value. Pinned in Task 15.
4. **Account too small for even one contract.** Every entry is rejected with reason `size_zero`, the run completes, and metrics with zero trades don't divide by zero. Pinned in Tasks 9 and 16.
5. **Duplicate rows for the same contract and timestamp in source data.** Validation keeps the last row and counts the rest as dropped. Pinned in Task 2.

---

### Task 1: Project scaffold, errors, logging

**Files:**
- Create: `pyproject.toml`, `.gitignore`, `src/options_bt/__init__.py`, `src/options_bt/errors.py`, `src/options_bt/logging_setup.py`
- Test: `tests/test_errors_logging.py`

**Interfaces:**
- Produces:
  - `errors.BacktestError(Exception)`, with subclasses `DataError`, `ConfigError` and `NoContractFound`.
  - `logging_setup.configure(log_file: Path | None = None, verbose: bool = False) -> None`. It configures the `options_bt` logger with a console handler (INFO, or DEBUG when `verbose`) and, when `log_file` is given, a DEBUG file handler. It is idempotent: calling it again replaces the handlers rather than adding duplicates.

- [ ] **Step 1: Create the scaffold**
  - `pyproject.toml`:
    - Build backend `hatchling`; `[project.scripts] options-bt = "options_bt.cli:main"`.
    - Runtime dependencies from Global Constraints; `[dependency-groups] dev = ["pytest", "ruff"]`.
    - `[tool.ruff] line-length = 100`, `target-version = "py312"`, lint `select = ["E","F","I","B","UP","SIM"]`.
    - `[tool.pytest.ini_options] testpaths = ["tests"]`.
  - `.gitignore`: `.venv/`, `__pycache__/`, `runs/`, `data/`, `*.egg-info/`, `.pytest_cache/`, `.ruff_cache/`.
  - Run `uv sync`. Expected: a lockfile is created and dependencies install.
  - `cli.py` doesn't exist yet. The script entry only matters once Task 20 adds it.

- [ ] **Step 2: Write failing tests**
```python
def test_error_hierarchy():
    for cls in (DataError, ConfigError, NoContractFound):
        assert issubclass(cls, BacktestError)

def test_configure_writes_debug_to_file_and_is_idempotent(tmp_path):
    log_file = tmp_path / "run.log"
    configure(log_file)
    configure(log_file)
    logging.getLogger("options_bt.x").debug("hello")
    assert log_file.read_text().count("hello") == 1
```

- [ ] **Step 3:** Run `uv run pytest tests/test_errors_logging.py -q`. Expected: FAIL (import error).
- [ ] **Step 4: Implement `errors.py` and `logging_setup.py`.** Log format: `"%(asctime)s %(levelname)s %(name)s: %(message)s"`. Set the logger's level to DEBUG and `propagate=False`.
- [ ] **Step 5:** Run the quality gate. Expected: all pass.
- [ ] **Step 6: Commit:** `git add -A && git commit -m "feat: project scaffold, errors, logging"`

---

### Task 2: Canonical quote schema and validation

**Files:**
- Create: `src/options_bt/data/__init__.py`, `src/options_bt/data/schema.py`
- Test: `tests/data/test_schema.py`

**Interfaces:**
- Produces:
  - `QUOTE_SCHEMA: dict[str, pl.DataType]`, with columns in this order:
    - `ts` (`pl.Datetime("us","UTC")`)
    - `underlying` (Utf8)
    - `underlying_price` (Float64)
    - `expiration` (Date)
    - `strike` (Float64)
    - `right` (Utf8, `"C"`/`"P"`)
    - `style` (Utf8)
    - `settlement` (Utf8)
    - `bid`, `ask`, `delta` (Float64)
    - `iv` (Float64, nullable)
    - `multiplier` (Int32)
  - `KEY_COLUMNS = ["ts","underlying","expiration","strike","right"]`
  - `validate(df: pl.DataFrame) -> tuple[pl.DataFrame, int]`. It returns rows cast to `QUOTE_SCHEMA` (in column order) and the dropped-row count.
  - `snapshot_ts(d: date, at: time = time(15, 45)) -> datetime`. It treats `d` + `at` as `America/New_York` local time and converts to UTC.

- [ ] **Step 1: Write failing tests** (build a 3-row valid frame in a helper `_rows(**overrides)`)
```python
def test_missing_column_raises_data_error():
    with pytest.raises(DataError, match="delta"):
        validate(_rows().drop("delta"))

def test_bad_quotes_dropped_and_counted():
    df = _rows(bid=[1.0, 2.0, -1.0], ask=[1.2, 1.5, 0.5])  # row1 bid>ask, row2 negative
    out, dropped = validate(df)
    assert out.height == 1 and dropped == 2

def test_zero_ask_dropped():
    _, dropped = validate(_rows(ask=[0.0, 1.0, 1.0], bid=[0.0, 0.9, 0.9]))
    assert dropped == 1

def test_duplicate_contract_rows_keep_last():          # Review Focus 5
    df = pl.concat([_rows().head(1), _rows(bid=[0.5, 0.5, 0.5]).head(1)])
    out, dropped = validate(df)
    assert out.height == 1 and dropped == 1 and out["bid"][0] == 0.5

def test_snapshot_ts_handles_dst():
    assert snapshot_ts(date(2026, 1, 5)).hour == 20   # EST
    assert snapshot_ts(date(2026, 7, 6)).hour == 19   # EDT
```

- [ ] **Step 2:** Run. Expected: FAIL.
- [ ] **Step 3: Implement.**
  - Cast with `strict=True`. Wrap polars cast errors in `DataError` naming the column.
  - Drop rule: `bid < 0 or ask <= 0 or bid > ask`.
  - Dedupe with `unique(subset=KEY_COLUMNS, keep="last", maintain_order=True)`.
  - Log a WARNING with the count when rows are dropped.
- [ ] **Step 4:** Run the quality gate. Expected: pass.
- [ ] **Step 5: Commit:** `feat: canonical quote schema and validation`

---

### Task 3: Synthetic chain generator and Parquet writer

**Files:**
- Create: `src/options_bt/data/adapters/__init__.py`, `src/options_bt/data/adapters/synthetic.py`, `src/options_bt/data/store.py` (writer part only)
- Test: `tests/data/test_synthetic.py`, `tests/conftest.py`

**Interfaces:**
- Consumes: `validate`, `snapshot_ts` (Task 2).
- Produces:
  - `synthetic.bs_price(spot, strike, t_years, rate, vol, right) -> float` and `bs_delta(...) -> float`. They use `scipy.stats.norm.cdf`. When `t_years <= 0` they return intrinsic value and delta (±1 if in the money, otherwise 0).
  - `synthetic.generate_chains(underlying: str, closes: Sequence[tuple[date, float]], *, vol=0.20, rate=0.0, strike_step=1.0, strike_range=(0.8, 1.2), max_dte=70, spread=0.10, style="american", settlement="physical") -> pl.DataFrame`.
    - Expirations: every Friday from the first date through `last date + max_dte`. A day lists the expirations with `0 ≤ dte ≤ max_dte`.
    - Strikes: multiples of `strike_step` within `strike_range × close`.
    - Quotes: `bid = max(0, theo − spread/2)`, `ask = theo + spread/2`.
    - `iv = vol`, `multiplier = 100`, `ts = snapshot_ts(date)`.
  - `synthetic.convert(raw_path: Path, data_root: Path, **kwargs) -> ImportSummary`. It reads a CSV with columns `date,underlying,close` and generates and writes chains for each underlying.
  - `store.ImportSummary` (frozen dataclass): `rows_written: int`, `rows_dropped: int`, `partitions: int`.
  - `store.write_quotes(df: pl.DataFrame, data_root: Path) -> ImportSummary`. It validates the frame, then writes `data_root/quotes/underlying=<U>/year=<Y>/part-<n>.parquet`, using the next free `n` so repeated imports don't overwrite. It appends the summary as JSON to `data_root/import_log.jsonl`.
  - `tests/conftest.py` fixture `make_store(tmp_path)`. It returns a function `(paths: dict[str, list[float]], start=date(2024,1,2), **gen_kwargs) -> Path`. That function generates business-day closes for each underlying, writes them, and returns `data_root`.

- [ ] **Step 1: Write failing tests**
```python
def test_bs_put_call_parity():
    c = bs_price(100, 100, 0.5, 0.03, 0.2, "C"); p = bs_price(100, 100, 0.5, 0.03, 0.2, "P")
    assert c - p == pytest.approx(100 - 100 * math.exp(-0.03 * 0.5), abs=1e-9)

def test_expiry_day_is_intrinsic():
    assert bs_price(95, 100, 0.0, 0.0, 0.2, "P") == 5.0

def test_generated_chain_shape_and_delta_sign():
    df = generate_chains("SPY", [(date(2024, 1, 2), 100.0)])
    assert set(df["right"]) == {"C", "P"}
    assert (df.filter(pl.col("right") == "P")["delta"] <= 0).all()
    assert (df["ask"] - df["bid"] <= 0.10 + 1e-9).all()

def test_write_quotes_partitions_and_log(tmp_path):
    df = generate_chains("SPY", [(date(2024, 12, 31), 100.0), (date(2025, 1, 2), 100.0)])
    s = write_quotes(df, tmp_path)
    assert s.partitions == 2 and s.rows_dropped >= 0
    assert (tmp_path / "quotes/underlying=SPY/year=2025").is_dir()
    assert len((tmp_path / "import_log.jsonl").read_text().splitlines()) == 1
```

- [ ] **Step 2:** Run. Expected: FAIL.
- [ ] **Step 3: Implement** the functions and the `make_store` fixture.
- [ ] **Step 4:** Run the quality gate. Expected: pass.
- [ ] **Step 5: Commit:** `feat: synthetic chain generator and parquet writer`

---

### Task 4: Quote store reads and history

**Files:**
- Modify: `src/options_bt/data/store.py`
- Create: `src/options_bt/data/chain.py`, `src/options_bt/data/history.py`
- Test: `tests/data/test_store.py`, `tests/data/test_history.py`

**Interfaces:**
- Consumes: `make_store` fixture, `write_quotes`.
- Produces:
  - `chain.ContractKey` (frozen dataclass): `underlying: str`, `expiration: date`, `strike: float`, `right: str`.
  - `chain.find_quote(chain: pl.DataFrame, key: ContractKey) -> dict | None`. It returns the row as a dict, or `None` if there's no match.
  - `store.QuoteStore(data_root: Path)` with:
    - `timestamps(underlyings: Sequence[str], start: date | None = None, end: date | None = None) -> list[datetime]`: sorted union of snapshot times, filtered by ET date.
    - `chain(underlying: str, ts: datetime) -> pl.DataFrame`: raises `DataError` when there are no rows. It caches one loaded `(underlying, year)` partition at a time, so a run reads each year once.
    - `underlying_series(underlying: str) -> pl.DataFrame`: columns `[ts, underlying_price]`, sorted.
    - `atm_iv_series(underlying: str, target_dte: int = 30) -> pl.DataFrame`: columns `[ts, atm_iv]`. For each ts, take the expiration whose DTE is closest to `target_dte`, then the strike nearest `underlying_price`, and use the mean `iv` of the call and put. Rows with null iv are skipped. The result is cached per underlying.
    - `fingerprint() -> dict[str, dict]`: `{partition_path: {"files": n, "bytes": b}}`.
    - `dropped_rows() -> int`: sum of `rows_dropped` in `import_log.jsonl`.
  - `history.History(store: QuoteStore, now: datetime)` with:
    - `underlying_prices(underlying: str, lookback: int) -> pl.Series`
    - `atm_iv(underlying: str, lookback: int, target_dte: int = 30) -> pl.Series`

    Both return the last `lookback` values with `ts <= now`.

- [ ] **Step 1: Write failing tests**
```python
def test_timestamps_and_chain(make_store):
    root = make_store({"SPY": [100.0] * 5})
    st = QuoteStore(root)
    ts = st.timestamps(["SPY"])
    assert len(ts) == 5 and ts == sorted(ts)
    assert st.chain("SPY", ts[0])["underlying"].unique().to_list() == ["SPY"]

def test_chain_missing_ts_raises(make_store):
    st = QuoteStore(make_store({"SPY": [100.0] * 2}))
    with pytest.raises(DataError):
        st.chain("SPY", datetime(2030, 1, 1, tzinfo=UTC))

def test_find_quote_none_when_absent(make_store):
    st = QuoteStore(make_store({"SPY": [100.0]}))
    c = st.chain("SPY", st.timestamps(["SPY"])[0])
    assert find_quote(c, ContractKey("SPY", date(2099, 1, 1), 1.0, "P")) is None

def test_history_never_sees_future(make_store):
    st = QuoteStore(make_store({"SPY": [100.0, 101.0, 102.0, 103.0]}))
    ts = st.timestamps(["SPY"])
    h = History(st, ts[1])
    assert h.underlying_prices("SPY", 10).to_list() == [100.0, 101.0]
    assert len(h.atm_iv("SPY", 10)) == 2
```

- [ ] **Step 2:** Run. Expected: FAIL.
- [ ] **Step 3: Implement.** Use `pl.scan_parquet(data_root/"quotes/underlying=U/**/*.parquet")` for series and timestamps, and `pl.read_parquet` of a single year directory for `chain`.
- [ ] **Step 4:** Run the quality gate. Expected: pass.
- [ ] **Step 5: Commit:** `feat: quote store reads and point-in-time history`

---

### Task 5: Market series (T-bill, VIX, VIX3M)

**Files:**
- Create: `src/options_bt/data/market.py`, `examples/market/tbill.csv`, `examples/market/vix.csv`, `examples/market/vix3m.csv`
- Test: `tests/data/test_market.py`

**Interfaces:**
- Produces:
  - `MarketData(series: dict[str, pl.DataFrame])`. Each frame has columns `date` (Date) and `value` (Float64), sorted.
  - `MarketData.load(data_root: Path) -> MarketData`. It reads every `data_root/market/*.csv` (name = file stem). A missing directory gives empty series.
  - `asof(name: str, ts: datetime) -> float | None`. It returns the last value with `date <= ts` (ET date), or `None` if there's none. It raises `DataError(f"market series '{name}' not loaded")` for an unknown name.
  - Example CSVs: business days from 2024-01-02 to 2024-12-31. Constant tbill 5.0, vix 15.0, vix3m 17.0, plus a vix spike to 30.0 (vix3m 25.0) on 2024-08-05.

- [ ] **Step 1: Write failing tests**
```python
def test_asof_uses_last_value_at_or_before(tmp_path):
    (tmp_path / "market").mkdir()
    (tmp_path / "market/vix.csv").write_text("date,value\n2024-01-02,15\n2024-01-04,20\n")
    m = MarketData.load(tmp_path)
    assert m.asof("vix", snapshot_ts(date(2024, 1, 3))) == 15.0
    assert m.asof("vix", snapshot_ts(date(2024, 1, 4))) == 20.0
    assert m.asof("vix", snapshot_ts(date(2023, 12, 29))) is None

def test_unknown_series_raises(tmp_path):
    with pytest.raises(DataError, match="vix3m"):
        MarketData.load(tmp_path).asof("vix3m", snapshot_ts(date(2024, 1, 2)))
```

- [ ] **Step 2:** Run. Expected: FAIL. **Step 3:** Implement and write the example CSVs with a short script. **Step 4:** Run the quality gate. **Step 5: Commit:** `feat: as-of market series`

---

### Task 6: Legs, payoff and max loss

**Files:**
- Create: `src/options_bt/engine/__init__.py`, `src/options_bt/engine/position.py`
- Test: `tests/engine/test_position.py`

**Interfaces:**
- Consumes: `ContractKey` (Task 4).
- Produces:
  - `Leg` (dataclass): `key: ContractKey`, `qty: int`, `style: str`, `settlement: str`, `multiplier: int = 100`, `entry_price: float = 0.0`.
  - `leg_value(legs: Sequence[Leg], prices: Sequence[float]) -> float`
  - `payoff_at_expiry(legs: Sequence[Leg], spot: float) -> float`: dollars per unit, intrinsic only.
  - `max_loss(legs: Sequence[Leg], net_premium: float) -> float | None`: dollars per unit, ≥ 0.
  - `Position` (dataclass): `id: int`, `underlying: str`, `legs: list[Leg]`, `quantity: int`, `opened_ts: datetime`, `entry_net: float` (per unit), `commissions: float`, `max_loss: float | None` (per unit), `realized: float = 0.0` (dollars, all units), `tags: dict = field(default_factory=dict)`. Property `earliest_expiration -> date`.
  - `TradeRecord` (dataclass): `position_id`, `underlying`, `opened_ts`, `closed_ts`, `legs: str` (e.g. `"-1 P 95.0 2024-02-16, +1 P 90.0 2024-02-16"`), `quantity`, `entry_net`, `exit_value`, `commissions`, `pnl`, `exit_reason`, `max_loss`.
- **`max_loss` algorithm:**
  - **Single expiration:** evaluate `payoff_at_expiry + net_premium` at spot 0 and at every strike. If the net call quantity (Σ qty of calls) is < 0, the loss is unbounded: return `None`. Otherwise `max_loss = max(0, −min(values))`.
  - **Multiple expirations:** greedily match each short leg to an unused long leg with the same right, `qty ≥ |short qty|` and `expiration ≥` the short's. With no match, return `None`.
    - The adverse gap for a put is `max(0, short.strike − long.strike)`; for a call it is `max(0, long.strike − short.strike)`.
    - `max_loss = max(0, Σ gap × |qty| × multiplier − net_premium)`.

- [ ] **Step 1: Write failing tests** (helper `L(qty, right, strike, exp=E1)` builds a `Leg`; `E1 = date(2024,2,16)`, `E2 = date(2024,3,15)`)
```python
def test_put_credit_spread_max_loss():
    legs = [L(-1, "P", 95), L(1, "P", 90)]
    assert max_loss(legs, net_premium=100.0) == 400.0          # 5-wide, $1.00 credit

def test_iron_condor_max_loss_is_one_wing():
    legs = [L(-1, "P", 95), L(1, "P", 90), L(-1, "C", 105), L(1, "C", 110)]
    assert max_loss(legs, net_premium=150.0) == 350.0

def test_long_butterfly_max_loss_is_debit():
    legs = [L(1, "C", 95), L(-2, "C", 100), L(1, "C", 105)]
    assert max_loss(legs, net_premium=-120.0) == 120.0

def test_naked_put_and_call_are_unbounded_or_large():
    assert max_loss([L(-1, "C", 100)], 200.0) is None
    assert max_loss([L(-1, "P", 100)], 200.0) == 9800.0         # bounded at spot 0

def test_calendar_and_diagonal():
    assert max_loss([L(-1, "P", 100, E1), L(1, "P", 100, E2)], -150.0) == 150.0
    assert max_loss([L(-1, "P", 100, E1), L(1, "P", 95, E2)], -50.0) == 550.0
    assert max_loss([L(-1, "P", 100, E2), L(1, "P", 100, E1)], 50.0) is None

def test_leg_value_sign_convention():
    legs = [L(-1, "P", 95), L(1, "P", 90)]
    assert leg_value(legs, [2.0, 1.0]) == -100.0
```

- [ ] **Step 2:** Run. Expected: FAIL. **Step 3:** Implement. **Step 4:** Run the quality gate. **Step 5: Commit:** `feat: legs, payoff and max loss`

---

### Task 7: Fill model and commissions

**Files:**
- Create: `src/options_bt/execution/__init__.py`, `src/options_bt/execution/fills.py`, `src/options_bt/execution/costs.py`
- Test: `tests/execution/test_fills_costs.py`

**Interfaces:**
- Consumes: `Leg`, `find_quote`.
- Produces:
  - `fills.DEFAULT_FILL_FRACTION = {1: 0.75, 2: 0.66, 3: 0.56, 4: 0.53}`
  - `fills.FillModel(fill_fraction: Mapping[int, float] = DEFAULT_FILL_FRACTION, override: float | None = None)`:
    - `fraction(n_legs: int) -> float`: the override if set, otherwise `fill_fraction[min(n_legs, max key)]`.
    - `leg_price(bid: float, ask: float, buying: bool, n_legs: int) -> float`: `bid + f×(ask−bid)` if buying, else `ask − f×(ask−bid)`.
    - `prices(chain: pl.DataFrame, legs: Sequence[Leg], opening: bool) -> list[float] | None`: per-share price for each leg. When opening, a leg with `qty > 0` buys; when closing, a leg with `qty < 0` buys. Returns `None` if any quote is missing.
  - `fills.mid_prices(chain, legs) -> list[float] | None`
  - `costs.commission(legs: Sequence[Leg], quantity: int, per_contract: float, per_order: float = 0.0) -> float`: `Σ|qty| × quantity × per_contract + per_order`.

- [ ] **Step 1: Write failing tests**
```python
def test_fraction_half_is_mid_and_one_is_cross():
    assert FillModel(override=0.5).leg_price(1.0, 1.2, True, 2) == pytest.approx(1.1)
    assert FillModel(override=1.0).leg_price(1.0, 1.2, False, 2) == pytest.approx(1.0)

def test_two_leg_default_fraction():
    assert FillModel().leg_price(1.0, 2.0, True, 2) == pytest.approx(1.66)
    assert FillModel().leg_price(1.0, 2.0, False, 2) == pytest.approx(1.34)

def test_more_than_four_legs_uses_largest_key():
    assert FillModel().fraction(6) == 0.53

def test_prices_none_when_quote_missing(spy_chain):   # small fixture chain in conftest
    leg = L(-1, "P", 12345.0)
    assert FillModel().prices(spy_chain, [leg], opening=True) is None

def test_commission():
    assert commission([L(-1, "P", 95), L(1, "P", 90)], 3, 0.65, 1.0) == pytest.approx(4.9)
```

- [ ] **Step 2:** Run. Expected: FAIL. **Step 3:** Implement. Move the `L` helper into `tests/conftest.py` and add a `spy_chain` fixture (one synthetic snapshot). **Step 4:** Run the quality gate. **Step 5: Commit:** `feat: fill model and commissions`

---

### Task 8: Portfolio and settlement

**Files:**
- Create: `src/options_bt/execution/settlement.py`, `src/options_bt/engine/portfolio.py`
- Test: `tests/engine/test_portfolio.py`

**Interfaces:**
- Consumes: Tasks 6 and 7.
- Produces:
  - `settlement.intrinsic(right: str, strike: float, spot: float) -> float`
  - `settlement.is_due(expiration: date, ts: datetime, session_close: time) -> bool`: true if `expiration < et_date(ts)`, or if `expiration == et_date(ts)` and the ET time `>= session_close`.
  - `Portfolio(initial_cash: float)` with attributes `cash`, `positions: dict[int, Position]` and `trades: list[TradeRecord]`, and methods:
    - `open(underlying, legs: list[Leg], quantity, ts, commission, max_loss, tags) -> Position`: `legs` already carry `entry_price`; `cash += entry_net × quantity − commission`.
    - `close(position_id, prices: list[float], ts, commission, reason) -> TradeRecord`: `cash += leg_value(legs, prices) × quantity − commission`.
    - `settle_expired(ts, spots: Mapping[str, float], session_close: time) -> list[TradeRecord]`: for each due leg, add `qty × intrinsic × multiplier × quantity` to `cash` and to `realized`, then remove the leg. A position with no legs left closes with reason `"assignment"` if any settled short leg was in the money with physical settlement, otherwise `"expired"`. Physical settlement is logged at INFO.
    - `mark(chains: Mapping[str, pl.DataFrame]) -> tuple[float, int]`: the total mid value of open positions, and the number of legs marked from a stale price. A missing quote uses the last known mid per `ContractKey`, falling back to `entry_price`.
    - `requirement(model) -> float`: Σ `model.requirement(legs, entry_net) × quantity` over open positions, using `entry_net` from open.

- [ ] **Step 1: Write failing tests**
```python
def test_open_close_cash_and_pnl():
    p = Portfolio(10_000)
    pos = p.open("SPY", [L(-1,"P",95,price=2.0), L(1,"P",90,price=1.0)], 2, T0, 2.6, 400.0, {})
    assert p.cash == pytest.approx(10_000 + 200 - 2.6)
    tr = p.close(pos.id, [0.5, 0.2], T1, 2.6, "profit_target")
    assert tr.pnl == pytest.approx((100 - 30) * 2 - 5.2)
    assert p.cash == pytest.approx(10_000 + tr.pnl)

def test_settlement_needs_only_spot_not_quote():                # Review Focus 1
    p = Portfolio(10_000)
    p.open("SPY", [L(-1,"P",95,price=2.0), L(1,"P",90,price=1.0)], 1, T0, 0.0, 400.0, {})
    trades = p.settle_expired(EXPIRY_TS, {"SPY": 92.0}, time(15, 45))
    assert trades[0].pnl == pytest.approx(100 - 300)
    assert trades[0].exit_reason == "assignment"

def test_holiday_expiration_settles_next_step():                # Review Focus 2
    assert is_due(date(2024, 3, 29), snapshot_ts(date(2024, 4, 1)), time(15, 45))
    assert not is_due(date(2024, 4, 5), snapshot_ts(date(2024, 4, 4)), time(15, 45))

def test_calendar_front_leg_settles_back_leg_stays():
    p = Portfolio(10_000)
    pos = p.open("SPY", [L(-1,"P",100,E1,price=1.0), L(1,"P",100,E2,price=2.5)], 1, T0, 0, 150.0, {})
    assert p.settle_expired(expiry_ts(E1), {"SPY": 101.0}, time(15, 45)) == []
    assert len(p.positions[pos.id].legs) == 1

def test_stale_mark_counted(spy_chain):
    p = Portfolio(10_000)
    p.open("SPY", [L(-1,"P",12345.0,price=2.0)], 1, T0, 0, None, {})
    value, stale = p.mark({"SPY": spy_chain})
    assert stale == 1 and value == pytest.approx(-200.0)
```
(Extend the `L` helper with `price=` and `exp=` keyword arguments.)

- [ ] **Step 2:** Run. Expected: FAIL. **Step 3:** Implement. Give `TradeRecord.exit_value` the per-unit value at exit plus realized settlements per unit. **Step 4:** Run the quality gate. **Step 5: Commit:** `feat: portfolio and expiration settlement`

---

### Task 9: Margin model and sizing

**Files:**
- Create: `src/options_bt/risk/__init__.py`, `src/options_bt/risk/margin.py`, `src/options_bt/risk/sizing.py`
- Test: `tests/risk/test_margin_sizing.py`

**Interfaces:**
- Produces:
  - `margin.MarginModel` (Protocol): `requirement(legs: Sequence[Leg], net_premium: float) -> float | None`.
  - `margin.DefinedRiskMargin`: returns `max_loss(legs, net_premium)`.
  - `margin.margin_model(name: str) -> MarginModel`: `"defined_risk"` gives `DefinedRiskMargin()`. Any other name raises `ConfigError`.
  - `sizing.size(requirement_per_unit: float | None, *, equity: float, cash: float, current_requirement: float, max_loss_pct_equity: float, max_total_max_loss_pct: float) -> tuple[int, str | None]`. It returns the quantity and a rejection reason. Reasons:
    - `"undefined_risk"`: the requirement is `None`.
    - `"size_zero"`: the per-trade budget is below one unit.
    - `"portfolio_cap"`: the portfolio cap leaves no room.
    - `"insufficient_cash"`: there isn't enough cash for one unit.

- [ ] **Step 1: Write failing tests**
```python
def test_size_by_max_loss_pct():
    assert size(400.0, equity=20_000, cash=20_000, current_requirement=0,
                max_loss_pct_equity=2.0, max_total_max_loss_pct=15) == (1, None)

def test_capped_by_portfolio_total():
    q, _ = size(400.0, equity=100_000, cash=100_000, current_requirement=14_000,
                max_loss_pct_equity=5.0, max_total_max_loss_pct=15)
    assert q == 2

def test_small_account_rejected_size_zero():                    # Review Focus 4
    assert size(400.0, equity=5_000, cash=5_000, current_requirement=0,
                max_loss_pct_equity=2.0, max_total_max_loss_pct=15) == (0, "size_zero")

def test_undefined_risk_rejected_by_defined_risk_margin():
    req = DefinedRiskMargin().requirement([L(-1, "C", 100)], 200.0)
    assert size(req, equity=1e6, cash=1e6, current_requirement=0,
                max_loss_pct_equity=2, max_total_max_loss_pct=15) == (0, "undefined_risk")

def test_unknown_margin_model():
    with pytest.raises(ConfigError):
        margin_model("reg_t")
```

- [ ] **Step 2:** Run. Expected: FAIL. **Step 3:** Implement. **Step 4:** Run the quality gate. **Step 5: Commit:** `feat: margin model and position sizing`

---

### Task 10: Strategy types and config models

**Files:**
- Create: `src/options_bt/strategy/__init__.py`, `src/options_bt/strategy/base.py`, `src/options_bt/strategy/config.py`
- Test: `tests/strategy/test_config.py`

**Interfaces:**
- Consumes: `Leg`, `Position`, `MarketData`, `History`, `FillModel`.
- Produces:
  - `base.OpenOrder` (dataclass): `underlying: str`, `legs: list[Leg]`, `reason: str`, `tags: dict`.
  - `base.CloseOrder` (dataclass): `position_id: int`, `reason: str`.
  - `Order = OpenOrder | CloseOrder`
  - `base.RunStats` (dataclass): `stale_marks: int = 0`, `deferred_closes: int = 0`, `skipped_entries: int = 0`, `spread_cost: float = 0.0` (dollars paid versus mid across all fills), `rejections: dict[str, int]` (default empty). Method `reject(reason: str) -> None`.
  - `base.StepContext` (dataclass): `ts`, `chains: Mapping[str, pl.DataFrame]`, `positions: Mapping[int, Position]`, `equity: float`, `market: MarketData`, `history: History`, `fill_model: FillModel`, `stats: RunStats`.
  - `base.Strategy` (Protocol): `on_step(ctx: StepContext) -> list[Order]`.
  - `config.py` pydantic models, all `model_config = ConfigDict(extra="forbid")`:
    - `LegSpec`:
      - `right` accepts `put`/`call`/`P`/`C` and normalises to `"P"`/`"C"`.
      - `side: Literal["long","short"]`, `ratio: int = 1`.
      - `dte: tuple[int,int] | None`, `delta: float | None`, `ref: int | None`, `strike_offset: float | None`.
      - Validator: exactly one of (`dte`+`delta`) or (`ref`+`strike_offset`) is required; `dte` is optional alongside `ref`.
    - `Schedule`: `weekdays: list[Literal["MON","TUE","WED","THU","FRI"]] | None`, `every_n_steps: int | None`.
    - `EntryConfig`: `schedule: Schedule = Schedule()`, `max_open_positions: int | None`, `filters: list[dict] = []`, `legs: list[LegSpec]` (min 1). A `ref` must point to an earlier index.
    - `ExitConfig`: `profit_target_pct`, `stop_loss_multiple`, `dte_exit` (all optional).
    - `SizingConfig`: `max_loss_pct_equity: float`.
    - `PortfolioCaps`: `max_total_max_loss_pct: float = 100.0`.
    - `CostConfig`: `commission_per_contract = 0.65`, `per_order_fee = 0.0`, `fill_fraction: dict[int,float] = DEFAULT_FILL_FRACTION`, `fill_fraction_override: float | None`.
    - `AccountConfig`: `initial_cash = 15000.0`, `cash_interest = False`, `session_close: time = time(15,45)`.
    - `StrategyConfig`: `name`, `underlyings: list[str]`, `entry`, `exits = ExitConfig()`, `sizing`, `portfolio_caps = PortfolioCaps()`, `costs = CostConfig()`, `account = AccountConfig()`, `margin_model = "defined_risk"`.
  - `config.load_raw(path: Path) -> dict`: YAML parse errors become `ConfigError`.
  - `config.parse_config(raw: dict) -> StrategyConfig`: a pydantic `ValidationError` becomes `ConfigError` listing each `loc` path and message.

- [ ] **Step 1: Write failing tests** (with `configs/examples` YAML inlined as a dict `PCS`, matching the spec's example)
```python
def test_example_config_parses():
    cfg = parse_config(PCS)
    assert cfg.entry.legs[0].right == "P" and cfg.entry.legs[1].ref == 0

def test_typo_names_the_field():
    bad = {**PCS, "exits": {"profit_target_pc": 50}}
    with pytest.raises(ConfigError, match="profit_target_pc"):
        parse_config(bad)

def test_leg_needs_selector():
    bad = copy.deepcopy(PCS); bad["entry"]["legs"][0].pop("delta")
    with pytest.raises(ConfigError, match="legs"):
        parse_config(bad)

def test_forward_ref_rejected():
    bad = copy.deepcopy(PCS); bad["entry"]["legs"][1]["ref"] = 1
    with pytest.raises(ConfigError):
        parse_config(bad)
```

- [ ] **Step 2:** Run. Expected: FAIL. **Step 3:** Implement. **Step 4:** Run the quality gate. **Step 5: Commit:** `feat: strategy types and validated config`

---

### Task 11: Leg selectors

**Files:**
- Create: `src/options_bt/strategy/selectors.py`
- Test: `tests/strategy/test_selectors.py`

**Interfaces:**
- Consumes: `LegSpec`, `Leg`, `ContractKey`, `NoContractFound`.
- Produces: `select_legs(chain: pl.DataFrame, specs: Sequence[LegSpec], ts: datetime) -> list[Leg]`. Legs come back with `entry_price = 0.0`, and `qty = ±ratio` (short is negative).
  - **dte + delta:** among expirations with `dte_min ≤ (exp − et_date(ts)).days ≤ dte_max`, take the one closest to the midpoint (ties go to the earlier one). Then take the strike of that right minimising `|abs(delta) − target|`.
  - **ref + strike_offset:** use the expiration of `specs[ref]` (or the `dte` rule if `dte` is given). The target is `ref strike + offset`; choose the nearest listed strike, with tolerance `max(0.01, 0.25 × |offset|)`, and it must differ from the ref strike.
  - Raises `NoContractFound` with a message naming the leg index and the rule.

- [ ] **Step 1: Write failing tests** (on a synthetic chain: spot 100, `strike_step=1`, a fixed `ts`)
```python
def test_put_credit_spread_selection(spy_chain_100):
    legs = select_legs(spy_chain_100, PCS_SPECS, TS)
    short, long = legs
    assert short.qty == -1 and long.qty == 1
    assert long.key.strike == short.key.strike - 5
    assert 30 <= (short.key.expiration - TS_DATE).days <= 45

def test_no_expiration_in_range_raises(spy_chain_100):
    spec = LegSpec(right="put", side="short", dte=(400, 500), delta=0.25)
    with pytest.raises(NoContractFound, match="leg 0"):
        select_legs(spy_chain_100, [spec], TS)

def test_offset_outside_tolerance_raises(spy_chain_100):
    specs = [PCS_SPECS[0], LegSpec(right="put", side="long", ref=0, strike_offset=-0.3)]
    with pytest.raises(NoContractFound):
        select_legs(spy_chain_100, specs, TS)
```

- [ ] **Step 2:** Run. Expected: FAIL. **Step 3:** Implement. **Step 4:** Run the quality gate. **Step 5: Commit:** `feat: leg selectors`

---

### Task 12: Entry filters

**Files:**
- Create: `src/options_bt/strategy/filters.py`, `configs/events.csv`
- Test: `tests/strategy/test_filters.py`

**Interfaces:**
- Consumes: `StepContext`.
- Produces:
  - `FILTERS: dict[str, Callable[..., bool]]` and a `register(name)` decorator.
  - `check(filter_cfg: dict, ctx: StepContext, underlying: str) -> bool`
  - `validate_filters(filter_cfgs: list[dict]) -> None`: raises `ConfigError` on an unknown `type` or on params the function doesn't accept (use `inspect.signature`).
  - Filters, each with signature `(ctx, underlying, **params) -> bool`:
    - `vix_term_structure(max_ratio: float = 1.0)`: `asof("vix") / asof("vix3m") < max_ratio`. Returns False (with a DEBUG log) if either value is `None`.
    - `iv_rank(min: float = 0, max: float = 100, lookback_days: int = 252)`: rank = `(last − low) / (high − low) × 100` over `history.atm_iv(underlying, lookback_days)`. Returns False when fewer than `lookback_days // 2` values exist, or when `high == low`.
    - `event_blackout(file: str = "configs/events.csv", days_before: int = 1, days_after: int = 0)`: returns False when any event date `d` satisfies `d − days_before ≤ et_date(ts) ≤ d + days_after`. The events file (columns `date,event`) is cached per path.
  - `configs/events.csv` holds the 2026 dates from the research report: CPI 2026-10-14, FOMC 2026-10-28, election 2026-11-03, FOMC 2026-12-09.

- [ ] **Step 1: Write failing tests** (a `ctx_factory` fixture builds a `StepContext` from a `make_store` root, a `MarketData`, and a ts)
```python
def test_vix_term_structure(ctx_factory):
    assert check({"type": "vix_term_structure", "max_ratio": 1.0}, ctx_factory(vix=15, vix3m=17), "SPY")
    assert not check({"type": "vix_term_structure", "max_ratio": 1.0}, ctx_factory(vix=30, vix3m=25), "SPY")

def test_iv_rank_needs_history(ctx_factory):
    assert not check({"type": "iv_rank", "min": 0, "lookback_days": 252}, ctx_factory(days=10), "SPY")

def test_event_blackout(tmp_path, ctx_factory):
    f = tmp_path / "ev.csv"; f.write_text("date,event\n2024-01-10,CPI\n")
    cfg = {"type": "event_blackout", "file": str(f), "days_before": 1}
    assert not check(cfg, ctx_factory(on=date(2024, 1, 9)), "SPY")
    assert check(cfg, ctx_factory(on=date(2024, 1, 11)), "SPY")

def test_unknown_filter_and_bad_param():
    with pytest.raises(ConfigError, match="nope"):
        validate_filters([{"type": "nope"}])
    with pytest.raises(ConfigError, match="max_ration"):
        validate_filters([{"type": "vix_term_structure", "max_ration": 1}])
```

- [ ] **Step 2:** Run. Expected: FAIL. **Step 3:** Implement, and add `ctx_factory` to conftest. **Step 4:** Run the quality gate. **Step 5: Commit:** `feat: entry filter registry`

---

### Task 13: Exit rules

**Files:**
- Create: `src/options_bt/strategy/exits.py`
- Test: `tests/strategy/test_exits.py`

**Interfaces:**
- Consumes: `ExitConfig`.
- Produces:
  - `ExitInputs` (dataclass): `pnl_per_unit: float`, `basis: float` (= `abs(entry_net)`), `dte: int` (calendar days to the earliest expiration).
  - `EXITS: dict[str, Callable[[ExitInputs, float], bool]]`, checked in order `profit_target_pct`, `stop_loss_multiple`, `dte_exit`:
    - `profit_target_pct`: `pnl ≥ v/100 × basis`
    - `stop_loss_multiple`: `−pnl ≥ v × basis`
    - `dte_exit`: `dte ≤ v`
  - `exit_reason(inputs: ExitInputs, cfg: ExitConfig) -> str | None`: returns the first matching key with the `_pct`/`_multiple` suffix removed (`"profit_target"`, `"stop_loss"`, `"dte_exit"`).

- [ ] **Step 1: Write failing tests**
```python
CFG = ExitConfig(profit_target_pct=50, stop_loss_multiple=2.0, dte_exit=21)

def test_profit_target(): assert exit_reason(ExitInputs(50.0, 100.0, 30), CFG) == "profit_target"
def test_stop_loss():     assert exit_reason(ExitInputs(-200.0, 100.0, 30), CFG) == "stop_loss"
def test_dte_exit():      assert exit_reason(ExitInputs(0.0, 100.0, 21), CFG) == "dte_exit"
def test_no_exit():       assert exit_reason(ExitInputs(10.0, 100.0, 30), CFG) is None
def test_unset_rules_ignored():
    assert exit_reason(ExitInputs(-1e6, 100.0, 0), ExitConfig()) is None
```

- [ ] **Step 2:** Run. Expected: FAIL. **Step 3:** Implement. **Step 4:** Run the quality gate. **Step 5: Commit:** `feat: exit rule registry`

---

### Task 14: RuleStrategy

**Files:**
- Create: `src/options_bt/strategy/rule_strategy.py`
- Test: `tests/strategy/test_rule_strategy.py`

**Interfaces:**
- Consumes: Tasks 10–13, `FillModel.prices`, `leg_value`.
- Produces: `RuleStrategy(config: StrategyConfig)`. The constructor calls `validate_filters(config.entry.filters)`. Its `on_step(ctx) -> list[Order]`:
  1. **Exits.** For each position whose `tags["strategy"] == config.name`:
     - Closing prices come from `ctx.fill_model.prices(chain, legs, opening=False)`. If they're `None`, skip the position this step.
     - Otherwise build `ExitInputs(pnl_per_unit = entry_net + leg_value(legs, prices) + realized / quantity, basis = abs(entry_net), dte = (earliest_expiration − et_date(ts)).days)` and emit `CloseOrder` if `exit_reason` returns a reason.
  2. **Entries.** These happen only on schedule:
     - Schedule rules: the ET weekday is in `weekdays` (if set), and the internal step counter `% every_n_steps == 0` (if set). With neither set, entries happen every step.
     - Skip when the count of open positions for this strategy is `≥ max_open_positions`.
     - For each underlying in `config.underlyings` that has a chain this step, apply all filters, then `select_legs`.
     - On `NoContractFound`: log at DEBUG, `ctx.stats.skipped_entries += 1`, and continue.
     - Emit `OpenOrder(underlying, legs, reason="entry", tags={"strategy": config.name})`.

- [ ] **Step 1: Write failing tests** (use `ctx_factory`; positions are created with `Portfolio.open`)
```python
def test_enters_on_scheduled_weekday_only(ctx_factory):
    s = RuleStrategy(parse_config(PCS))                         # weekdays [MON, THU]
    assert any(isinstance(o, OpenOrder) for o in s.on_step(ctx_factory(on=date(2024, 1, 8))))  # Monday
    assert s.on_step(ctx_factory(on=date(2024, 1, 9))) == []                                 # Tuesday

def test_profit_target_emits_close(ctx_factory):
    ctx = ctx_factory(on=date(2024, 1, 9), open_pcs_with_credit=5.0)  # rich credit, cheap now
    orders = RuleStrategy(parse_config(PCS)).on_step(ctx)
    assert [o.reason for o in orders if isinstance(o, CloseOrder)] == ["profit_target"]

def test_no_contract_counts_skip(ctx_factory):
    cfg = copy.deepcopy(PCS); cfg["entry"]["legs"][0]["dte"] = [400, 500]
    ctx = ctx_factory(on=date(2024, 1, 8))
    assert RuleStrategy(parse_config(cfg)).on_step(ctx) == [] and ctx.stats.skipped_entries == 1

def test_max_open_positions_respected(ctx_factory):
    cfg = copy.deepcopy(PCS); cfg["entry"]["max_open_positions"] = 1
    ctx = ctx_factory(on=date(2024, 1, 8), open_pcs_with_credit=1.0)
    assert not any(isinstance(o, OpenOrder) for o in RuleStrategy(parse_config(cfg)).on_step(ctx))
```

- [ ] **Step 2:** Run. Expected: FAIL. **Step 3:** Implement, and extend `ctx_factory` with an `open_pcs_with_credit` option. **Step 4:** Run the quality gate. **Step 5: Commit:** `feat: declarative rule strategy`

---

### Task 15: Step loop

**Files:**
- Create: `src/options_bt/engine/loop.py`
- Test: `tests/engine/test_loop.py`

**Interfaces:**
- Consumes: everything above.
- Produces:
  - `RunResult` (dataclass): `trades: pl.DataFrame` (one row per `TradeRecord`, columns named like its fields), `equity: pl.DataFrame` (columns `ts, equity, cash, open_positions, requirement, tbill`), `stats: RunStats`.
  - `run(config: StrategyConfig, store: QuoteStore, market: MarketData, strategy: Strategy | None = None, start: date | None = None, end: date | None = None) -> RunResult`. `strategy` defaults to `RuleStrategy(config)`. For each ts, follow the spec §5 order:
    1. Load the chains for underlyings present at that ts.
    2. Settle with `spots` taken from each chain's `underlying_price`.
    3. Mark positions and add the stale count to `stats`.
    4. Optionally accrue cash interest: `cash *= 1 + tbill/100 × days_since_last_step/365`.
    5. Build the `StepContext` with `equity = cash + mark value`, then call `on_step`.
    6. Closes first. When prices are `None`, `stats.deferred_closes += 1`.
    7. Opens:
       - Price with `FillModel.prices(opening=True)`, then set each leg's `entry_price`.
       - `net = −leg_value(legs, prices)`; `req = margin.requirement(legs, net)`.
       - Call `size(...)`. If the quantity is 0, call `stats.reject(reason)` and log it at DEBUG.
       - Otherwise compute `commission` and `portfolio.open(... max_loss=req ...)`.
       - For every fill (opens and closes), add `|leg_value(legs, prices) − leg_value(legs, mid_prices)| × quantity` to `stats.spread_cost`.
    8. Record the equity row (`tbill = market.asof("tbill", ts)` when loaded, else `None`).
  - On the last ts, force-close every open position with reason `"end_of_data"`. If prices are missing, settle each leg at intrinsic value using the last spot.
  - Log one INFO line per opened and closed trade, and INFO at start and end with the trade count and final equity.

- [ ] **Step 1: Write failing tests** (end-to-end on synthetic stores; PCS config with `weekdays: null`, `max_open_positions: 1`, no filters, `initial_cash: 100000`)
```python
def test_flat_path_spread_expires_worthless(make_store):
    root = make_store({"SPY": [100.0] * 60}, vol=0.2)
    res = run(no_exit_cfg(), QuoteStore(root), MarketData({}))
    first = res.trades.row(0, named=True)
    assert first["exit_reason"] == "expired"
    assert first["pnl"] == pytest.approx(first["entry_net"] * first["quantity"] - first["commissions"])

def test_crash_path_loses_max_loss_plus_costs(make_store):
    root = make_store({"SPY": [100.0] * 5 + [70.0] * 55})
    res = run(no_exit_cfg(), QuoteStore(root), MarketData({}))
    t = res.trades.row(0, named=True)
    assert t["pnl"] == pytest.approx(-t["max_loss"] * t["quantity"] - t["commissions"])

def test_profit_target_closes_early(make_store):
    root = make_store({"SPY": [100 + i for i in range(60)]})
    res = run(pt_cfg(50), QuoteStore(root), MarketData({}))
    assert res.trades["exit_reason"][0] == "profit_target"

def test_open_positions_closed_at_end_of_data(make_store):          # Review Focus 3
    root = make_store({"SPY": [100.0] * 10})
    res = run(no_exit_cfg(), QuoteStore(root), MarketData({}))
    assert res.trades["exit_reason"].to_list()[-1] == "end_of_data"
    assert res.equity["equity"][-1] == pytest.approx(100_000 + res.trades["pnl"].sum())

def test_tiny_account_runs_with_zero_trades(make_store):           # Review Focus 4
    cfg = no_exit_cfg(initial_cash=1_000)
    res = run(cfg, QuoteStore(make_store({"SPY": [100.0] * 10})), MarketData({}))
    assert res.trades.height == 0 and res.stats.rejections["size_zero"] > 0
```

- [ ] **Step 2:** Run. Expected: FAIL. **Step 3:** Implement. **Step 4:** Run the quality gate. **Step 5: Commit:** `feat: step loop`

---

### Task 16: Metrics

**Files:**
- Create: `src/options_bt/analytics/__init__.py`, `src/options_bt/analytics/metrics.py`
- Test: `tests/analytics/test_metrics.py`

**Interfaces:**
- Consumes: the `RunResult.equity` and `trades` schemas.
- Produces:
  - `periods_per_year(ts: pl.Series) -> float` = `(n − 1) / years`, where `years = (last − first).days / 365.25`.
  - `annualized_return(equity: pl.DataFrame) -> float` = `(last/first) ** (1/years) − 1`, or 0.0 if `years == 0`.
  - `max_drawdown(equity: pl.DataFrame) -> tuple[float, int]`: drawdown as a positive fraction, and the longest underwater stretch in calendar days.
  - `sharpe(equity) -> float | None` and `sortino(equity) -> float | None`:
    - Excess returns = step returns − `tbill/100 / ppy` (a null tbill counts as 0).
    - Annualize by `√ppy`.
    - Return `None` when there are fewer than 2 returns or the standard deviation is 0.
  - `trade_stats(trades: pl.DataFrame) -> dict`: keys `trades`, `win_rate`, `avg_win`, `avg_loss`, `profit_factor`, `worst_trade`, `total_commissions`. Every value is `None`-safe when there are 0 trades.
  - `compute_metrics(equity, trades, stats: RunStats, dropped_rows: int) -> dict`. It merges all of the above with:
    - `net_return`
    - `annualized_return`
    - `annualized_tbill` (mean tbill / 100, or `None`)
    - `excess_annualized_return`
    - `max_drawdown`, `max_drawdown_days`
    - the data-quality counts
    - `total_spread_cost` (from `stats.spread_cost`)
    - `costs_pct_gross_pnl` = `(commissions + spread_cost) / (Σ pnl + commissions + spread_cost)`, or `None` when that denominator is ≤ 0

- [ ] **Step 1: Write failing tests** (helper `eq(values, start=date(2024,1,2), tbill=None)` builds an equity frame on business days)
```python
def test_max_drawdown():
    assert max_drawdown(eq([100, 110, 99, 120]))[0] == pytest.approx(0.1)

def test_annualized_return_one_year():
    e = pl.DataFrame({"ts": [snapshot_ts(date(2024,1,2)), snapshot_ts(date(2025,1,1))],
                      "equity": [100.0, 110.0]})
    assert annualized_return(e) == pytest.approx(0.10, rel=1e-2)

def test_sharpe_none_for_constant_equity():
    assert sharpe(eq([100.0] * 10)) is None

def test_trade_stats_empty_is_safe():                                # Review Focus 4
    s = trade_stats(pl.DataFrame(schema={"pnl": pl.Float64, "commissions": pl.Float64}))
    assert s["trades"] == 0 and s["win_rate"] is None

def test_spread_cost_in_metrics():
    m = compute_metrics(eq([100.0, 101.0]), pl.DataFrame({"pnl": [10.0], "commissions": [2.0]}),
                        RunStats(spread_cost=8.0), dropped_rows=0)
    assert m["costs_pct_gross_pnl"] == pytest.approx(0.5)

def test_profit_factor():
    s = trade_stats(pl.DataFrame({"pnl": [100.0, -50.0, 50.0], "commissions": [1.0] * 3}))
    assert s["profit_factor"] == pytest.approx(3.0) and s["win_rate"] == pytest.approx(2 / 3)
```

- [ ] **Step 2:** Run. Expected: FAIL. **Step 3:** Implement. **Step 4:** Run the quality gate. **Step 5: Commit:** `feat: performance metrics`

---

### Task 17: Stress periods, in/out-of-sample split, criteria

**Files:**
- Create: `src/options_bt/analytics/periods.py`, `src/options_bt/analytics/criteria.py`, `configs/stress_periods.yaml`, `configs/criteria.yaml`
- Test: `tests/analytics/test_periods_criteria.py`

**Interfaces:**
- Consumes: the `compute_metrics` inputs.
- Produces:
  - `Period` (dataclass): `name`, `start: date`, `end: date`. `load_periods(path) -> list[Period]`.
  - `stress_table(equity, periods) -> list[dict]`: rows of `{name, return, max_drawdown}`. Periods with fewer than 2 equity rows get `None` values.
  - `split_metrics(equity, trades, oos_start: date) -> dict`: `{"in_sample": {...}, "out_of_sample": {...}}`, each holding `net_return`, `annualized_return`, `max_drawdown` and `trades`. Trades are split by `closed_ts`.
  - `Criteria` (pydantic, `extra="forbid"`): `min_net_return = 0.0`, `min_excess_return = 0.0`, `max_drawdown = 0.25`, `max_stress_loss = 0.15`, `min_oos_net_return = 0.0`, `min_robustness = 0.60`. `load_criteria(path) -> Criteria` (a `ConfigError` on bad keys).
  - `CheckResult` (dataclass): `name`, `status: Literal["PASS","FAIL","N/A"]`, `actual`, `threshold`.
  - `evaluate(criteria, metrics: dict, stress: list[dict], split: dict | None, robustness: float | None = None) -> list[CheckResult]`. The checks, in order:
    1. `net_return`
    2. `excess_return` (N/A when tbill is missing)
    3. `max_drawdown`
    4. `worst_stress_loss`: the worst period return compared to `−max_stress_loss`; N/A when all are None.
    5. `oos_net_return`: N/A without a split.
    6. `robustness`: N/A when None.
  - `configs/stress_periods.yaml`: GFC 2008-09-01–2009-03-31, Volmageddon 2018-02-01–2018-02-28, COVID 2020-02-01–2020-04-30, 2022 bear 2022-01-01–2022-12-31, Aug 2024 2024-08-01–2024-08-31, Tariff shock 2025-04-01–2025-04-30.

- [ ] **Step 1: Write failing tests**
```python
def test_stress_table_period_return():
    rows = stress_table(eq([100, 90, 95], start=date(2018, 2, 1)),
                        [Period("V", date(2018, 2, 1), date(2018, 2, 28))])
    assert rows[0]["return"] == pytest.approx(-0.05)

def test_evaluate_pass_fail_na():
    m = {"net_return": 0.2, "excess_annualized_return": None, "max_drawdown": 0.3}
    res = {r.name: r.status for r in evaluate(Criteria(), m, [{"name": "x", "return": -0.2}], None)}
    assert res == {"net_return": "PASS", "excess_return": "N/A", "max_drawdown": "FAIL",
                   "worst_stress_loss": "FAIL", "oos_net_return": "N/A", "robustness": "N/A"}

def test_split_by_oos_start():
    s = split_metrics(eq([100, 101, 102, 103]), EMPTY_TRADES, oos_start=date(2024, 1, 4))
    assert s["out_of_sample"]["net_return"] == pytest.approx(103 / 102 - 1)
```

- [ ] **Step 2:** Run. Expected: FAIL. **Step 3:** Implement and write both YAML files. **Step 4:** Run the quality gate. **Step 5: Commit:** `feat: stress periods, oos split, go/no-go criteria`

---

### Task 18: Run outputs and report

**Files:**
- Create: `src/options_bt/analytics/report.py`
- Test: `tests/analytics/test_report.py`

**Interfaces:**
- Consumes: Tasks 15–17.
- Produces:
  - `make_run_dir(root: Path, name: str) -> Path`: `root/<YYYYmmddTHHMMSSZ>_<name>/`, created on call.
  - `provenance(data_root: Path, store: QuoteStore) -> dict`: `git_commit` (from `git rev-parse HEAD`, or `None` on failure), `data_root`, `fingerprint`.
  - `render_report(name: str, metrics: dict, stress: list[dict], split: dict | None, checks: list[CheckResult]) -> str`. Markdown with these sections in order: `# <name>`, `## Go/no-go`, `## Metrics`, `## Stress periods`, `## In-sample vs out-of-sample` (only when there's a split), `## Data quality`.
  - `plot_equity(equity: pl.DataFrame, path: Path) -> None`: two stacked axes (equity, drawdown) using matplotlib's `Agg` backend.
  - `write_outputs(run_dir, result: RunResult, metrics, stress, split, checks, resolved_config: dict) -> None`. It writes `config.yaml`, `trades.parquet`, `trades.csv`, `equity.parquet`, `metrics.json` (with `default=str`), `report.md` and `equity_drawdown.png`. `run.log` is written by `logging_setup`.

- [ ] **Step 1: Write failing tests**
```python
def test_report_sections_and_checks():
    md = render_report("pcs", {"net_return": 0.1}, [], None,
                       [CheckResult("net_return", "PASS", 0.1, 0.0)])
    assert md.index("## Go/no-go") < md.index("## Metrics")
    assert "| net_return | PASS |" in md
    assert "In-sample" not in md

def test_write_outputs_creates_all_files(tmp_path, small_result):  # small_result: a RunResult from a 10-day synthetic run
    write_outputs(tmp_path, small_result, {"net_return": 0.0}, [], None, [], {"name": "x"})
    for f in ["config.yaml", "trades.csv", "trades.parquet", "equity.parquet",
              "metrics.json", "report.md", "equity_drawdown.png"]:
        assert (tmp_path / f).exists(), f
```

- [ ] **Step 2:** Run. Expected: FAIL. **Step 3:** Implement. **Step 4:** Run the quality gate. **Step 5: Commit:** `feat: run outputs and markdown report`

---

### Task 19: Parameter sweeps

**Files:**
- Create: `src/options_bt/sweep.py`
- Test: `tests/test_sweep.py`

**Interfaces:**
- Consumes: `parse_config`, `run`, `compute_metrics`.
- Produces:
  - `expand(raw: dict) -> tuple[dict[str, list], list[tuple[dict[str, Any], dict]]]`. It walks `raw` recursively. Any dict of exactly `{"sweep": [...]}` is a grid axis, keyed by a dotted path (e.g. `"exits.profit_target_pct"`, or `"entry.legs.0.delta"` for list indices). It returns the grid and the list of `(params, concrete_raw)` for the Cartesian product, in `itertools.product` order.
  - `robustness(rows: list[dict], grid: dict[str, list]) -> float | None`. `rows` holds the params plus `net_return` and `annualized_return`. The best row is the one with the highest `annualized_return`. Neighbours are rows whose grid index differs from the best's by at most 1 on every axis, excluding the best itself. The result is the fraction of neighbours with `net_return > 0`, or `None` when there are no neighbours.
  - `run_sweep(raw: dict, store, market, out_dir: Path, start=None, end=None) -> pl.DataFrame`. It runs each combination, logs progress at INFO (`"sweep 3/12 {params}"`), writes `sweep_results.parquet` and `.csv` to `out_dir`, and returns the frame. It doesn't write per-combination run folders.

- [ ] **Step 1: Write failing tests**
```python
def test_expand_marker_not_plain_lists():
    raw = {"underlyings": ["SPY"], "exits": {"profit_target_pct": {"sweep": [25, 50]},
           "dte_exit": {"sweep": [14, 21]}}, "entry": {"legs": [{"dte": [30, 45]}]}}
    grid, combos = expand(raw)
    assert grid == {"exits.profit_target_pct": [25, 50], "exits.dte_exit": [14, 21]}
    assert len(combos) == 4 and combos[0][1]["entry"]["legs"][0]["dte"] == [30, 45]

def test_robustness():
    grid = {"a": [1, 2, 3]}
    rows = [{"a": 1, "net_return": 0.1, "annualized_return": 0.05},
            {"a": 2, "net_return": 0.2, "annualized_return": 0.09},
            {"a": 3, "net_return": -0.1, "annualized_return": -0.02}]
    assert robustness(rows, grid) == pytest.approx(0.5)

def test_run_sweep_rows(tmp_path, make_store):
    raw = sweepable_pcs(profit=[25, 50])
    df = run_sweep(raw, QuoteStore(make_store({"SPY": [100.0] * 20})), MarketData({}), tmp_path)
    assert df.height == 2 and (tmp_path / "sweep_results.csv").exists()
```

- [ ] **Step 2:** Run. Expected: FAIL. **Step 3:** Implement. **Step 4:** Run the quality gate. **Step 5: Commit:** `feat: parameter sweeps with robustness score`

---

### Task 20: CLI, example configs and the synthetic demo

**Files:**
- Create: `src/options_bt/cli.py`, `configs/pcs_spy_45dte.yaml` (the spec §6 example), `examples/spy_path.csv` (about 250 business days of SPY closes from 2024-01-02, generated as a seeded random walk with a −15% drawdown in August), `README.md` (replacing the stub)
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: everything above.
- Produces `main(argv: list[str] | None = None) -> int` with these subcommands:
  - `run CONFIG --data-root PATH [--start D] [--end D] [--oos-start D] [--runs-dir runs] [--criteria configs/criteria.yaml] [--stress configs/stress_periods.yaml] [-v]`
    - Create the run dir and call `configure(run_dir/"run.log", verbose)`.
    - Load and parse the config, then run.
    - Compute metrics, the stress table, the split (when `--oos-start` is given) and the checks.
    - `write_outputs`, print the run dir path and the go/no-go table, and return 0.
  - `sweep CONFIG --data-root PATH [...]`: the out dir is a run dir named `sweep_<name>`. It prints the path and the robustness score.
  - `data import synthetic RAW --data-root PATH`, and `data import tabular RAW --mapping M --data-root PATH`. The tabular command is wired up in Task 21.
  - On `BacktestError`, print `error: <message>` to stderr and return 2. Other exceptions propagate.
- README: what the project is, `uv sync`, the demo commands (`data import synthetic examples/spy_path.csv --data-root data/demo`, copy `examples/market` to `data/demo/market`, then `run configs/pcs_spy_45dte.yaml --data-root data/demo`), how to add a data source, and how to add a filter or exit.

- [ ] **Step 1: Write failing tests**
```python
def test_end_to_end_demo(tmp_path):
    root = tmp_path / "data"
    assert main(["data", "import", "synthetic", "examples/spy_path.csv", "--data-root", str(root)]) == 0
    shutil.copytree("examples/market", root / "market")
    assert main(["run", "configs/pcs_spy_45dte.yaml", "--data-root", str(root),
                 "--runs-dir", str(tmp_path / "runs")]) == 0
    run_dir = next((tmp_path / "runs").iterdir())
    assert (run_dir / "report.md").read_text().startswith("# pcs_spy_45dte")
    assert "INFO" in (run_dir / "run.log").read_text()

def test_config_error_exit_code(tmp_path, capsys):
    bad = tmp_path / "bad.yaml"; bad.write_text("name: x\nbogus: 1\n")
    assert main(["run", str(bad), "--data-root", str(tmp_path), "--runs-dir", str(tmp_path)]) == 2
    assert "error:" in capsys.readouterr().err
```

- [ ] **Step 2:** Run. Expected: FAIL. **Step 3:** Implement. Generate `examples/spy_path.csv` with a short seeded script (seed 7); the script itself isn't committed. **Step 4:** Run the quality gate, plus `uv run options-bt run configs/pcs_spy_45dte.yaml --data-root <demo>` by hand. Expected: a run folder whose `report.md` contains a go/no-go table. **Step 5: Commit:** `feat: CLI, example config and synthetic demo`

---

### Task 21: Mapping-driven tabular importer

**Files:**
- Create: `src/options_bt/data/adapters/tabular.py`, `configs/mappings/dubach.yaml`, `configs/mappings/orats.yaml`
- Modify: `src/options_bt/cli.py` (wire `data import tabular`)
- Test: `tests/data/test_tabular.py`, `tests/data/samples/long_sample.csv`, `tests/data/samples/wide_sample.csv`

**Interfaces:**
- Consumes: `write_quotes`, `snapshot_ts`.
- Produces:
  - `Mapping` (pydantic, `extra="forbid"`):
    - `format: Literal["csv","parquet"]`, `layout: Literal["long","wide"]`
    - `date_column: str`, `date_format: str | None`, `snapshot_time: time = time(15,45)`
    - `columns: dict[str, str]`: canonical name → source column, for `underlying`, `underlying_price`, `expiration`, `strike`, and in long layout also `right`, `bid`, `ask`, `delta`, `iv`.
    - `right_values: dict[str, str] = {"C": "C", "P": "P"}`: canonical value → source value (long layout).
    - `call: dict[str,str] | None`, `put: dict[str,str] | None`: canonical → source for `bid`, `ask`, `delta`, `iv` (wide layout).
    - `put_delta_from_call: bool = False`: when true, put delta = call delta − 1.
    - `defaults: dict[str, Any] = {}`: e.g. `style`, `settlement`, `multiplier`.
    - `verified: bool = False`
  - `load_mapping(path) -> Mapping` (`ConfigError` on bad keys).
  - `convert(raw_path: Path, mapping_path: Path, data_root: Path) -> ImportSummary`. Wide rows are reshaped to one call row and one put row. When a required canonical column is missing after mapping, it raises `DataError` naming the column. When `verified` is false, it logs a WARNING `"mapping <name> is unverified; check a sample before trusting results"`.
  - `dubach.yaml` and `orats.yaml` record the column names their documentation describes, with `verified: false` and a comment pointing to the source docs URL. **Look up both docs when implementing this task;** if they can't be reached, leave the mapping keys as placeholders in a commented block and say so in the task report.

- [ ] **Step 1: Write failing tests**
```python
def test_long_layout(tmp_path):
    s = convert(SAMPLES / "long_sample.csv", SAMPLES / "long_mapping.yaml", tmp_path)
    assert s.rows_written == 4
    assert set(QuoteStore(tmp_path).chain("SPY", QuoteStore(tmp_path).timestamps(["SPY"])[0])["right"]) == {"C", "P"}

def test_wide_layout_put_delta_from_call(tmp_path):
    convert(SAMPLES / "wide_sample.csv", SAMPLES / "wide_mapping.yaml", tmp_path)
    st = QuoteStore(tmp_path); c = st.chain("SPY", st.timestamps(["SPY"])[0])
    put = c.filter(pl.col("right") == "P").row(0, named=True)
    assert put["delta"] == pytest.approx(0.4 - 1)

def test_missing_column_names_it(tmp_path):
    with pytest.raises(DataError, match="delta"):
        convert(SAMPLES / "long_sample_no_delta.csv", SAMPLES / "long_mapping.yaml", tmp_path)
```
(Samples and their test mappings live in `tests/data/samples/`, with 2 rows per layout.)

- [ ] **Step 2:** Run. Expected: FAIL. **Step 3:** Implement and wire the CLI. **Step 4:** Run the quality gate. **Step 5: Commit:** `feat: mapping-driven tabular importer`

---

### Task 22: Final verification

- [ ] **Step 1:** `uv run pytest -q`. Expected: all pass in under 30s (check the reported duration).
- [ ] **Step 2:** `uv run ruff check . && uv run ruff format --check .`. Expected: clean.
- [ ] **Step 3:** Run the README demo commands from a clean temp directory. Expected: the run folder holds all 8 files, and `report.md` shows the go/no-go table and stress rows (N/A for periods outside 2024).
- [ ] **Step 4:** Commit any fixes, then push: `git push -u origin claude/stoic-einstein-bu0ky9`.
