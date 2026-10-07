class BacktestError(Exception):
    """Base class for all deliberately raised backtest errors."""


class DataError(BacktestError):
    pass


class ConfigError(BacktestError):
    pass


class NoContractFound(BacktestError):
    pass
