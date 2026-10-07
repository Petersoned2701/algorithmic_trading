"""Writes a backtest run's output folder: data files, markdown report and chart."""

import json
import logging
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import polars as pl
import yaml

from options_bt.analytics.criteria import CheckResult
from options_bt.data.store import QuoteStore
from options_bt.engine.loop import RunResult

log = logging.getLogger(__name__)

_DATA_QUALITY_KEYS = (
    "stale_marks",
    "deferred_closes",
    "skipped_entries",
    "rejections",
    "dropped_rows",
)
_OOS_WARNING = "Out-of-sample window has no closed trades; treat the OOS check with caution."


def make_run_dir(root: Path, name: str) -> Path:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    run_dir = root / f"{stamp}_{name}"
    run_dir.mkdir(parents=True)
    return run_dir


def provenance(data_root: Path, store: QuoteStore) -> dict:
    commit = None
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=False
        )
        if proc.returncode == 0:
            commit = proc.stdout.strip() or None
    except OSError:
        log.warning("could not determine git commit")
    return {"git_commit": commit, "data_root": str(data_root), "fingerprint": store.fingerprint()}


def _fmt(value: object) -> str:
    if value is None:
        return "—"
    if isinstance(value, float):
        return f"{value:.4g}"
    if isinstance(value, dict):
        return ", ".join(f"{k}={v}" for k, v in value.items()) or "—"
    return str(value)


def _table(header: list[str], rows: list[list[object]]) -> list[str]:
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    lines += ["| " + " | ".join(_fmt(cell) for cell in row) + " |" for row in rows]
    return lines


def render_report(
    name: str,
    metrics: dict,
    stress: list[dict],
    split: dict | None,
    checks: list[CheckResult],
) -> str:
    lines = [f"# {name}", "", "## Go/no-go", ""]
    lines += _table(
        ["Check", "Status", "Actual", "Threshold"],
        [[c.name, c.status, c.actual, c.threshold] for c in checks],
    )
    lines += ["", "## Metrics", ""]
    lines += _table(["Metric", "Value"], [[k, v] for k, v in metrics.items()])
    lines += ["", "## Stress periods", ""]
    lines += _table(
        ["Period", "Return", "Max drawdown"],
        [[row["name"], row["return"], row["max_drawdown"]] for row in stress],
    )
    if split is not None:
        sides = [("In-sample", split["in_sample"]), ("Out-of-sample", split["out_of_sample"])]
        lines += ["", "## In-sample vs out-of-sample", ""]
        lines += _table(
            ["Side", "Net return", "Annualized return", "Max drawdown", "Trades"],
            [
                [
                    label,
                    side["net_return"],
                    side["annualized_return"],
                    side["max_drawdown"],
                    side["trades"],
                ]
                for label, side in sides
            ],
        )
        if split["out_of_sample"]["trades"] == 0:
            lines += ["", _OOS_WARNING]
    lines += ["", "## Data quality", ""]
    lines += _table(
        ["Item", "Value"], [[k, metrics[k]] for k in _DATA_QUALITY_KEYS if k in metrics]
    )
    return "\n".join(lines) + "\n"


def plot_equity(equity: pl.DataFrame, path: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, (ax_equity, ax_dd) = plt.subplots(2, 1, sharex=True, figsize=(10, 6))
    try:
        if len(equity):
            ts = equity["ts"].to_list()
            values = equity["equity"]
            drawdown = (values / values.cum_max() - 1).to_list()
            ax_equity.plot(ts, values.to_list())
            ax_dd.fill_between(ts, drawdown, 0, color="tab:red", alpha=0.4)
        ax_equity.set_ylabel("Equity ($)")
        ax_dd.set_ylabel("Drawdown")
        fig.tight_layout()
        fig.savefig(path)
    finally:
        plt.close(fig)


def write_outputs(
    run_dir: Path,
    result: RunResult,
    metrics: dict,
    stress: list[dict],
    split: dict | None,
    checks: list[CheckResult],
    resolved_config: dict,
) -> None:
    config = json.loads(json.dumps(resolved_config, default=str))
    (run_dir / "config.yaml").write_text(yaml.safe_dump(config, sort_keys=False))
    result.trades.write_parquet(run_dir / "trades.parquet")
    result.trades.write_csv(run_dir / "trades.csv")
    result.equity.write_parquet(run_dir / "equity.parquet")
    (run_dir / "metrics.json").write_text(json.dumps(metrics, indent=2, default=str))
    name = str(resolved_config.get("name", run_dir.name))
    (run_dir / "report.md").write_text(render_report(name, metrics, stress, split, checks))
    plot_equity(result.equity, run_dir / "equity_drawdown.png")
    log.info("wrote run outputs to %s", run_dir)
