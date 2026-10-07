import pytest

from options_bt.data.history import History
from options_bt.data.store import QuoteStore


def test_history_never_sees_future(make_store):
    st = QuoteStore(make_store({"SPY": [100.0, 101.0, 102.0, 103.0]}))
    ts = st.timestamps(["SPY"])
    h = History(st, ts[1])
    assert h.underlying_prices("SPY", 10).to_list() == [100.0, 101.0]
    assert len(h.atm_iv("SPY", 10)) == 2


def test_history_returns_last_lookback_values(make_store):
    st = QuoteStore(make_store({"SPY": [100.0, 101.0, 102.0, 103.0]}, vol=0.3))
    ts = st.timestamps(["SPY"])
    h = History(st, ts[2])
    assert h.underlying_prices("SPY", 2).to_list() == [101.0, 102.0]
    iv = h.atm_iv("SPY", 2)
    assert iv.len() == 2 and iv.to_list() == pytest.approx([0.3, 0.3])


def test_history_includes_now_inclusive(make_store):
    st = QuoteStore(make_store({"SPY": [100.0, 101.0]}))
    ts = st.timestamps(["SPY"])
    assert History(st, ts[0]).underlying_prices("SPY", 5).to_list() == [100.0]
