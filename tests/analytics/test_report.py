import json
import re
import subprocess

import polars as pl
import yaml

from options_bt.analytics.criteria import CheckResult
from options_bt.analytics.report import (
    make_run_dir,
    plot_equity,
    provenance,
    render_report,
    write_outputs,
)
from options_bt.data.store import QuoteStore

OUTPUT_FILES = [
    "config.yaml",
    "trades.csv",
    "trades.parquet",
    "equity.parquet",
    "metrics.json",
    "report.md",
    "equity_drawdown.png",
]


def test_report_sections_and_checks():
    md = render_report(
        "pcs", {"net_return": 0.1}, [], None, [CheckResult("net_return", "PASS", 0.1, 0.0)]
    )
    assert md.index("## Go/no-go") < md.index("## Metrics")
    assert "| net_return | PASS |" in md
    assert "In-sample" not in md


def test_report_section_order_and_formats():
    metrics = {
        "net_return": 0.123456,
        "sharpe": None,
        "rejections": {"cap": 2, "margin": 1},
        "stale_marks": 3,
        "deferred_closes": 0,
        "skipped_entries": 1,
        "dropped_rows": 4,
    }
    stress = [{"name": "covid", "return": -0.05, "max_drawdown": 0.08}]
    side = {"net_return": 0.1, "annualized_return": 0.1, "max_drawdown": 0.05, "trades": 3}
    split = {"in_sample": side, "out_of_sample": side}
    checks = [
        CheckResult("net_return", "PASS", 0.123456, 0.0),
        CheckResult("robustness", "N/A", None, 0.6),
    ]
    md = render_report("pcs", metrics, stress, split, checks)
    headings = re.findall(r"^#{1,2} .*$", md, flags=re.M)
    assert headings == [
        "# pcs",
        "## Go/no-go",
        "## Metrics",
        "## Stress periods",
        "## In-sample vs out-of-sample",
        "## Data quality",
    ]
    assert "| Check | Status | Actual | Threshold |" in md
    assert "| net_return | PASS | 0.1235 | 0 |" in md
    assert "| robustness | N/A | — | 0.6 |" in md
    assert "| Metric | Value |" in md
    assert "| sharpe | — |" in md
    assert "| rejections | cap=2, margin=1 |" in md
    assert "| Period | Return | Max drawdown |" in md
    assert "| covid | -0.05 | 0.08 |" in md
    assert "OOS check with caution" not in md
    data_quality = md.split("## Data quality")[1]
    for key in ("stale_marks", "deferred_closes", "skipped_entries", "rejections", "dropped_rows"):
        assert key in data_quality


def test_report_warns_when_oos_has_no_trades():
    in_sample = {"net_return": 0.1, "annualized_return": 0.1, "max_drawdown": 0.0, "trades": 3}
    out_of_sample = {**in_sample, "trades": 0}
    md = render_report("x", {}, [], {"in_sample": in_sample, "out_of_sample": out_of_sample}, [])
    assert "Out-of-sample window has no closed trades; treat the OOS check with caution." in md


def test_make_run_dir_creates_timestamped_folder(tmp_path):
    run_dir = make_run_dir(tmp_path, "pcs")
    assert run_dir.is_dir()
    assert run_dir.parent == tmp_path
    assert re.fullmatch(r"\d{8}T\d{6}Z_pcs", run_dir.name)


def test_provenance_fingerprint_and_git(make_store):
    root = make_store({"SPY": [100.0] * 3})
    info = provenance(root, QuoteStore(root))
    assert info["data_root"] == str(root)
    assert info["fingerprint"] == QuoteStore(root).fingerprint()
    assert info["git_commit"] is None or re.fullmatch(r"[0-9a-f]{40}", info["git_commit"])


def test_provenance_git_failure_gives_none(make_store, monkeypatch):
    def boom(*args, **kwargs):
        raise FileNotFoundError("git")

    monkeypatch.setattr(subprocess, "run", boom)
    root = make_store({"SPY": [100.0] * 3})
    assert provenance(root, QuoteStore(root))["git_commit"] is None


def test_provenance_nonzero_git_exit_gives_none(make_store, monkeypatch):
    def failed(*args, **kwargs):
        return subprocess.CompletedProcess(args, 128, stdout="", stderr="fatal")

    monkeypatch.setattr(subprocess, "run", failed)
    root = make_store({"SPY": [100.0] * 3})
    assert provenance(root, QuoteStore(root))["git_commit"] is None


def test_plot_equity_writes_png_and_handles_empty(small_result, tmp_path):
    plot_equity(small_result.equity, tmp_path / "a.png")
    plot_equity(small_result.equity.clear(), tmp_path / "empty.png")
    for name in ("a.png", "empty.png"):
        assert (tmp_path / name).read_bytes().startswith(b"\x89PNG")


def test_write_outputs_creates_all_files(tmp_path, small_result):
    write_outputs(tmp_path, small_result, {"net_return": 0.0}, [], None, [], {"name": "x"})
    for f in OUTPUT_FILES:
        assert (tmp_path / f).exists(), f


def test_write_outputs_contents(tmp_path, small_result):
    from datetime import date, time

    cfg = {"name": "x", "when": date(2024, 1, 2), "at": time(15, 45)}
    metrics = {"net_return": 0.0, "when": date(2024, 1, 2)}
    write_outputs(tmp_path, small_result, metrics, [], None, [], cfg)
    assert yaml.safe_load((tmp_path / "config.yaml").read_text()) == {
        "name": "x",
        "when": "2024-01-02",
        "at": "15:45:00",
    }
    assert json.loads((tmp_path / "metrics.json").read_text())["when"] == "2024-01-02"
    assert pl.read_parquet(tmp_path / "trades.parquet").shape == small_result.trades.shape
    assert pl.read_parquet(tmp_path / "equity.parquet").shape == small_result.equity.shape
    assert (tmp_path / "report.md").read_text().startswith("# x")
