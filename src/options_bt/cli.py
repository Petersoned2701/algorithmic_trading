"""The `options-bt` command line."""

import argparse
import json
import sys
from datetime import date
from pathlib import Path

from options_bt.analytics.criteria import evaluate, load_criteria
from options_bt.analytics.metrics import compute_metrics
from options_bt.analytics.periods import load_periods, split_metrics, stress_table
from options_bt.analytics.report import checks_table, make_run_dir, provenance, write_outputs
from options_bt.data.adapters import synthetic, tabular
from options_bt.data.market import MarketData
from options_bt.data.store import ImportSummary, QuoteStore
from options_bt.engine.loop import run
from options_bt.errors import BacktestError
from options_bt.logging_setup import configure
from options_bt.strategy.config import load_raw, parse_config
from options_bt.sweep import expand, robustness, run_sweep


def _common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("config", type=Path)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--start", type=date.fromisoformat)
    parser.add_argument("--end", type=date.fromisoformat)
    parser.add_argument("--runs-dir", type=Path, default=Path("runs"))
    parser.add_argument("-v", "--verbose", action="store_true")


_REPLACE_HELP = "overwrite (underlying, year) partitions that already hold data"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="options-bt", description="Options backtesting engine")
    commands = parser.add_subparsers(dest="command", required=True)

    run_cmd = commands.add_parser("run", help="backtest one strategy config")
    _common(run_cmd)
    run_cmd.add_argument("--oos-start", type=date.fromisoformat)
    run_cmd.add_argument("--criteria", type=Path, default=Path("configs/criteria.yaml"))
    run_cmd.add_argument("--stress", type=Path, default=Path("configs/stress_periods.yaml"))
    run_cmd.set_defaults(handler=_run)

    sweep_cmd = commands.add_parser("sweep", help="run every combination of {sweep: [...]} axes")
    _common(sweep_cmd)
    sweep_cmd.set_defaults(handler=_sweep)

    data_cmd = commands.add_parser("data", help="data management")
    data_actions = data_cmd.add_subparsers(dest="data_command", required=True)
    import_cmd = data_actions.add_parser("import", help="import raw quotes into a data root")
    sources = import_cmd.add_subparsers(dest="source", required=True)
    synthetic_cmd = sources.add_parser("synthetic", help="generate Black-Scholes chains")
    synthetic_cmd.add_argument("raw", type=Path, help="CSV with date,underlying,close")
    synthetic_cmd.add_argument("--data-root", type=Path, required=True)
    synthetic_cmd.add_argument("--replace", action="store_true", help=_REPLACE_HELP)
    synthetic_cmd.set_defaults(handler=_import_synthetic)
    tabular_cmd = sources.add_parser("tabular", help="convert a vendor CSV/Parquet via a mapping")
    tabular_cmd.add_argument("raw", type=Path, help="vendor CSV or Parquet file")
    tabular_cmd.add_argument("--mapping", type=Path, required=True)
    tabular_cmd.add_argument("--data-root", type=Path, required=True)
    tabular_cmd.add_argument("--replace", action="store_true", help=_REPLACE_HELP)
    tabular_cmd.set_defaults(handler=_import_tabular)
    return parser


def _run(args: argparse.Namespace) -> int:
    config = parse_config(load_raw(args.config))
    criteria = load_criteria(args.criteria)
    periods = load_periods(args.stress)

    run_dir = make_run_dir(args.runs_dir, config.name)
    configure(run_dir / "run.log", args.verbose)
    store = QuoteStore(args.data_root)
    market = MarketData.load(args.data_root)
    result = run(config, store, market, start=args.start, end=args.end)

    metrics = compute_metrics(result.equity, result.trades, result.stats, store.dropped_rows())
    stress = stress_table(result.equity, periods)
    split = None
    if args.oos_start is not None:
        split = split_metrics(result.equity, result.trades, args.oos_start)
    checks = evaluate(criteria, metrics, stress, split)
    resolved = {
        **config.model_dump(mode="json"),
        "provenance": provenance(args.data_root, store),
    }
    write_outputs(run_dir, result, metrics, stress, split, checks, resolved)

    print(run_dir)
    print("\n".join(checks_table(checks)))
    return 0


def _sweep(args: argparse.Namespace) -> int:
    raw = load_raw(args.config)
    out_dir = make_run_dir(args.runs_dir, f"sweep_{raw.get('name', args.config.stem)}")
    configure(out_dir / "run.log", args.verbose)
    store = QuoteStore(args.data_root)
    market = MarketData.load(args.data_root)
    frame = run_sweep(raw, store, market, out_dir, start=args.start, end=args.end)

    # run_sweep writes list-valued axes as JSON text, so match the grid to that.
    grid = {
        axis: [json.dumps(v) if isinstance(v, list | dict) else v for v in values]
        for axis, values in expand(raw)[0].items()
    }
    score = robustness(frame.to_dicts(), grid)
    print(out_dir)
    print(f"robustness: {'n/a' if score is None else f'{score:.2f}'}")
    return 0


def _import_synthetic(args: argparse.Namespace) -> int:
    return _print_summary(
        synthetic.convert(args.raw, args.data_root, replace=args.replace), args.data_root
    )


def _import_tabular(args: argparse.Namespace) -> int:
    return _print_summary(
        tabular.convert(args.raw, args.mapping, args.data_root, replace=args.replace),
        args.data_root,
    )


def _print_summary(summary: ImportSummary, data_root: Path) -> int:
    print(
        f"wrote {summary.rows_written} rows ({summary.rows_dropped} dropped) "
        f"in {summary.partitions} partitions under {data_root}"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        return args.handler(args)
    except BacktestError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
