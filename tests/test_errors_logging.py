import logging

from options_bt.errors import BacktestError, ConfigError, DataError, NoContractFound
from options_bt.logging_setup import configure


def test_error_hierarchy():
    for cls in (DataError, ConfigError, NoContractFound):
        assert issubclass(cls, BacktestError)


def test_configure_writes_debug_to_file_and_is_idempotent(tmp_path):
    log_file = tmp_path / "run.log"
    configure(log_file)
    configure(log_file)
    logging.getLogger("options_bt.x").debug("hello")
    assert log_file.read_text().count("hello") == 1
