from datetime import date

import polars as pl
import pytest

from options_bt.analytics.criteria import CheckResult, Criteria, evaluate, load_criteria
from options_bt.analytics.periods import Period, load_periods, split_metrics, stress_table
from options_bt.data.schema import snapshot_ts
from options_bt.errors import ConfigError
from tests.helpers import eq

EMPTY_TRADES = pl.DataFrame(
    {"closed_ts": [], "pnl": [], "commissions": []},
    schema={
        "closed_ts": pl.Datetime("us", "UTC"),
        "pnl": pl.Float64,
        "commissions": pl.Float64,
    },
)

V = Period("V", date(2018, 2, 1), date(2018, 2, 28))


def trades(*closes: date) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "closed_ts": [snapshot_ts(d) for d in closes],
            "pnl": [10.0] * len(closes),
            "commissions": [1.0] * len(closes),
        }
    )


def test_stress_table_period_return():
    rows = stress_table(eq([100, 90, 95], start=date(2018, 2, 1)), [V])
    assert rows[0]["return"] == pytest.approx(-0.05)
    assert rows[0]["name"] == "V"
    assert rows[0]["max_drawdown"] == pytest.approx(0.10)


def test_stress_table_bounds_inclusive_and_excludes_outside():
    # Feb 1 (Thu) .. Feb 28 (Wed) inclusive; the rows before/after are ignored.
    values = [1000, 100, 80, 120, 5000]
    equity = eq(values, start=date(2018, 1, 31))
    rows = stress_table(equity, [Period("P", date(2018, 2, 1), date(2018, 2, 2))])
    assert rows[0]["return"] == pytest.approx(80 / 100 - 1)


def test_stress_table_too_few_rows_gives_none():
    rows = stress_table(
        eq([100, 101], start=date(2024, 1, 2)),
        [Period("empty", date(2018, 2, 1), date(2018, 2, 28)), V],
    )
    assert rows == [
        {"name": "empty", "return": None, "max_drawdown": None},
        {"name": "V", "return": None, "max_drawdown": None},
    ]


def test_stress_table_single_row_period_is_none():
    rows = stress_table(
        eq([100, 90], start=date(2018, 2, 1)), [Period("one", date(2018, 2, 1), date(2018, 2, 1))]
    )
    assert rows[0]["return"] is None


def test_split_by_oos_start():
    s = split_metrics(eq([100, 101, 102, 103]), EMPTY_TRADES, oos_start=date(2024, 1, 4))
    assert s["out_of_sample"]["net_return"] == pytest.approx(103 / 102 - 1)
    assert s["in_sample"]["net_return"] == pytest.approx(101 / 100 - 1)
    assert set(s["in_sample"]) == {"net_return", "annualized_return", "max_drawdown", "trades"}


def test_split_oos_start_row_belongs_to_out_of_sample():
    s = split_metrics(eq([100, 101, 102, 103]), EMPTY_TRADES, oos_start=date(2024, 1, 3))
    assert s["in_sample"]["net_return"] == 0.0  # single row
    assert s["out_of_sample"]["net_return"] == pytest.approx(103 / 101 - 1)


def test_split_drawdown_and_annualized_per_side():
    s = split_metrics(eq([100, 80, 90, 120, 60]), EMPTY_TRADES, oos_start=date(2024, 1, 5))
    assert s["in_sample"]["max_drawdown"] == pytest.approx(0.2)
    assert s["out_of_sample"]["max_drawdown"] == pytest.approx(0.5)
    assert s["in_sample"]["annualized_return"] == pytest.approx(0.9 ** (365.25 / 2) - 1)
    assert s["out_of_sample"]["annualized_return"] == pytest.approx(0.5 ** (365.25 / 3) - 1)


def test_split_trades_by_closed_ts():
    t = trades(date(2024, 1, 2), date(2024, 1, 3), date(2024, 1, 4), date(2024, 1, 5))
    s = split_metrics(eq([100, 101, 102, 103]), t, oos_start=date(2024, 1, 4))
    assert s["in_sample"]["trades"] == 2
    assert s["out_of_sample"]["trades"] == 2


def test_split_empty_side():
    s = split_metrics(eq([100, 101]), EMPTY_TRADES, oos_start=date(2030, 1, 1))
    assert s["out_of_sample"] == {
        "net_return": 0.0,
        "annualized_return": 0.0,
        "max_drawdown": 0.0,
        "trades": 0,
    }


def test_criteria_defaults_and_extra_forbidden():
    c = Criteria()
    assert (c.min_net_return, c.min_excess_return, c.max_drawdown) == (0.0, 0.0, 0.25)
    assert (c.max_stress_loss, c.min_oos_net_return, c.min_robustness) == (0.15, 0.0, 0.60)
    with pytest.raises(ValueError):
        Criteria(bogus=1)


def test_evaluate_pass_fail_na():
    m = {"net_return": 0.2, "excess_annualized_return": None, "max_drawdown": 0.3}
    res = {r.name: r.status for r in evaluate(Criteria(), m, [{"name": "x", "return": -0.2}], None)}
    assert res == {
        "net_return": "PASS",
        "excess_return": "N/A",
        "max_drawdown": "FAIL",
        "worst_stress_loss": "FAIL",
        "oos_net_return": "N/A",
        "robustness": "N/A",
    }


def test_evaluate_all_pass_with_actuals_and_thresholds():
    m = {"net_return": 0.2, "excess_annualized_return": 0.05, "max_drawdown": 0.1}
    stress = [{"name": "a", "return": -0.05}, {"name": "b", "return": None}]
    split = {"in_sample": {}, "out_of_sample": {"net_return": 0.03}}
    res = evaluate(Criteria(), m, stress, split, robustness=0.7)
    assert [r.name for r in res] == [
        "net_return",
        "excess_return",
        "max_drawdown",
        "worst_stress_loss",
        "oos_net_return",
        "robustness",
    ]
    assert all(r.status == "PASS" for r in res)
    by = {r.name: r for r in res}
    assert by["worst_stress_loss"] == CheckResult("worst_stress_loss", "PASS", -0.05, -0.15)
    assert by["max_drawdown"].threshold == 0.25
    assert by["robustness"].actual == 0.7 and by["robustness"].threshold == 0.60


def test_evaluate_boundaries():
    m = {"net_return": 0.0, "excess_annualized_return": 0.0, "max_drawdown": 0.25}
    stress = [{"name": "a", "return": -0.15}]
    split = {"out_of_sample": {"net_return": 0.0}}
    res = {r.name: r.status for r in evaluate(Criteria(), m, stress, split, robustness=0.60)}
    assert res == {
        "net_return": "FAIL",  # strictly greater
        "excess_return": "FAIL",
        "max_drawdown": "PASS",  # <=
        "worst_stress_loss": "PASS",  # >= -max
        "oos_net_return": "FAIL",
        "robustness": "PASS",  # >=
    }


def test_evaluate_missing_metrics_and_all_none_stress_are_na():
    res = {
        r.name: r.status for r in evaluate(Criteria(), {}, [{"name": "a", "return": None}], None)
    }
    assert set(res.values()) == {"N/A"}
    res = {r.name: r.status for r in evaluate(Criteria(), {}, [], None)}
    assert res["worst_stress_loss"] == "N/A"


def test_load_periods(tmp_path):
    p = tmp_path / "p.yaml"
    p.write_text("- {name: A, start: 2020-02-01, end: '2020-04-30'}\n")
    assert load_periods(p) == [Period("A", date(2020, 2, 1), date(2020, 4, 30))]


@pytest.mark.parametrize(
    "text",
    [
        "name: A\n",  # not a list
        "- {name: A, start: 2020-02-01}\n",  # missing end
        "- {name: A, start: nope, end: 2020-04-30}\n",  # bad date
        "- {name: A, start: 2020-05-01, end: 2020-04-30}\n",  # end before start
        "- just a string\n",
        "- [unclosed\n",
    ],
)
def test_load_periods_malformed(tmp_path, text):
    p = tmp_path / "bad.yaml"
    p.write_text(text)
    with pytest.raises(ConfigError, match="bad.yaml"):
        load_periods(p)


def test_load_periods_missing_file(tmp_path):
    with pytest.raises(ConfigError, match="nope.yaml"):
        load_periods(tmp_path / "nope.yaml")


def test_shipped_stress_periods():
    periods = load_periods("configs/stress_periods.yaml")
    assert [p.name for p in periods] == [
        "GFC",
        "Volmageddon",
        "COVID",
        "2022 bear",
        "Aug 2024",
        "Tariff shock",
    ]
    assert periods[0] == Period("GFC", date(2008, 9, 1), date(2009, 3, 31))
    assert periods[5] == Period("Tariff shock", date(2025, 4, 1), date(2025, 4, 30))


def test_shipped_criteria_matches_defaults():
    assert load_criteria("configs/criteria.yaml") == Criteria()


def test_load_criteria_bad_key(tmp_path):
    p = tmp_path / "c.yaml"
    p.write_text("max_drawdown: 0.2\nbogus: 1\n")
    with pytest.raises(ConfigError, match="bogus"):
        load_criteria(p)
