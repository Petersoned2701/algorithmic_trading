from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import polars as pl
import yaml
from pydantic import BaseModel, ValidationError

from options_bt.errors import ConfigError, DataError


def load_yaml(path: Path | str, kind: type = dict) -> Any:
    """Parse a YAML file whose top level must be a `dict` (mapping) or `list`."""
    path = Path(path)
    try:
        raw = yaml.safe_load(path.read_text())
    except OSError as exc:
        raise ConfigError(f"cannot read {path}: {exc}") from exc
    except yaml.YAMLError as exc:
        raise ConfigError(f"invalid YAML in {path}: {exc}") from exc
    if not isinstance(raw, kind):
        shape = "mapping" if kind is dict else "list"
        raise ConfigError(f"{path} must be a YAML {shape} at the top level")
    return raw


def validate_model[M: BaseModel](model_cls: type[M], raw: Any, source: str = "") -> M:
    """Validate `raw`; errors list one dotted `loc: msg` per line, headed by `invalid {source}`."""
    try:
        return model_cls.model_validate(raw)
    except ValidationError as exc:
        lines = [f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()]
        header = [f"invalid {source}:"] if source else []
        raise ConfigError("\n".join([*header, *lines])) from exc


@contextmanager
def _unreadable(what: str, path: Path) -> Iterator[None]:
    try:
        yield
    except (OSError, pl.exceptions.PolarsError) as exc:
        raise DataError(f"cannot read {what} {path}: {exc}") from exc


def read_csv_or_raise(path: Path | str, what: str, **kwargs) -> pl.DataFrame:
    with _unreadable(what, Path(path)):
        return pl.read_csv(path, **kwargs)


def read_dated_csv(path: Path | str, what: str, floats: Sequence[str] = ()) -> pl.DataFrame:
    """A CSV with an ISO `date` column, sorted by it, and `floats` columns cast to float."""
    with _unreadable(what, Path(path)):
        df = pl.read_csv(path, schema_overrides={c: pl.Utf8 for c in ("date", *floats)})
        return df.select(
            pl.col("date").str.to_date("%Y-%m-%d", strict=True),
            *(pl.col(c).cast(pl.Float64, strict=True) for c in floats),
        ).sort("date")
