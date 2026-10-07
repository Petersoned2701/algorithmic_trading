import shutil
from pathlib import Path

import pytest

from options_bt.cli import main
from options_bt.strategy.config import load_raw, parse_config


@pytest.fixture
def demo_root(tmp_path):
    root = tmp_path / "data"
    assert (
        main(["data", "import", "synthetic", "examples/spy_path.csv", "--data-root", str(root)])
        == 0
    )
    shutil.copytree("examples/market", root / "market")
    return root


def test_end_to_end_demo(tmp_path, demo_root, capsys):
    runs = tmp_path / "runs"
    code = main(
        ["run", "configs/demo_pcs_synthetic.yaml", "--data-root", str(demo_root)]
        + ["--runs-dir", str(runs), "--oos-start", "2024-09-01"]
    )
    assert code == 0
    run_dir = next(runs.iterdir())
    report = (run_dir / "report.md").read_text()
    assert report.startswith("# demo_pcs_synthetic")
    assert "## Go/no-go" in report and "In-sample" in report
    assert "INFO" in (run_dir / "run.log").read_text()
    assert len((run_dir / "trades.csv").read_text().splitlines()) >= 2
    out = capsys.readouterr().out
    assert out.splitlines()[0] == str(run_dir)
    assert "max_drawdown" in out and "robustness" in out


def test_sweep_writes_results(tmp_path, demo_root, capsys):
    cfg = tmp_path / "sweep.yaml"
    cfg.write_text(
        Path("configs/demo_pcs_synthetic.yaml")
        .read_text()
        .replace("max_loss_pct_equity: 2.0", "max_loss_pct_equity: {sweep: [1.0, 2.0]}")
    )
    runs = tmp_path / "runs"
    code = main(["sweep", str(cfg), "--data-root", str(demo_root), "--runs-dir", str(runs)])
    assert code == 0
    sweep_dir = next(runs.iterdir())
    assert sweep_dir.name.endswith("_sweep_demo_pcs_synthetic")
    assert (sweep_dir / "sweep_results.csv").exists()
    assert "INFO" in (sweep_dir / "run.log").read_text()
    lines = capsys.readouterr().out.splitlines()
    assert lines[0] == str(sweep_dir)
    assert lines[1].startswith("robustness: ")


def test_config_error_exit_code(tmp_path, capsys):
    bad = tmp_path / "bad.yaml"
    bad.write_text("name: x\nbogus: 1\n")
    code = main(
        ["run", str(bad), "--data-root", str(tmp_path), "--runs-dir", str(tmp_path / "runs")]
    )
    assert code == 2
    assert "error:" in capsys.readouterr().err


def test_missing_data_exit_code(tmp_path, capsys):
    code = main(
        ["run", "configs/demo_pcs_synthetic.yaml", "--data-root", str(tmp_path / "none")]
        + ["--runs-dir", str(tmp_path / "runs")]
    )
    assert code == 2
    assert "error:" in capsys.readouterr().err


def test_import_twice_needs_replace_flag(demo_root, capsys):
    args = ["data", "import", "synthetic", "examples/spy_path.csv", "--data-root", str(demo_root)]
    capsys.readouterr()
    assert main(args) == 2
    assert "--replace" in capsys.readouterr().err
    assert main([*args, "--replace"]) == 0


def test_shipped_pcs_spy_config_parses():
    config = parse_config(load_raw(Path("configs/pcs_spy_45dte.yaml")))
    assert config.name == "pcs_spy_45dte" and config.underlyings == ["SPY"]
