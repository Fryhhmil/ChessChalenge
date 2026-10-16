"""Carrega o config.toml em dataclasses tipadas."""

from __future__ import annotations

import dataclasses
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover
    import tomli as tomllib

from .time_manager import TimeConfig


@dataclass(frozen=True)
class EngineConfig:
    path: Path
    threads: int = 4
    hash_mb: int = 256
    syzygy_path: Optional[Path] = None
    syzygy_probe_limit: int = 5


@dataclass(frozen=True)
class Config:
    engine: EngineConfig
    book_path: Optional[Path] = None
    book_max_plies: int = 10
    log_dir: Path = Path("logs")
    ponder: bool = True
    time: TimeConfig = field(default_factory=TimeConfig)


def _resolve(base: Path, value: Optional[str]) -> Optional[Path]:
    if not value:
        return None
    path = Path(value)
    return path if path.is_absolute() else (base / path).resolve()


def load_config(path: Path | str) -> Config:
    path = Path(path).resolve()
    with open(path, "rb") as fh:
        data = tomllib.load(fh)
    base = path.parent

    eng = data.get("engine", {})
    if "path" not in eng:
        raise ValueError("config: [engine] path é obrigatório")
    probe_limit = int(eng.get("syzygy_probe_limit", 5))
    if not 0 <= probe_limit <= 5:
        raise ValueError("config: syzygy_probe_limit deve estar entre 0 e 5 (regra da competição)")
    engine = EngineConfig(
        path=_resolve(base, eng["path"]),
        threads=int(eng.get("threads", 4)),
        hash_mb=int(eng.get("hash_mb", 256)),
        syzygy_path=_resolve(base, eng.get("syzygy_path")),
        syzygy_probe_limit=probe_limit,
    )

    book = data.get("book", {})
    max_plies = int(book.get("max_plies", 10))
    if not 0 <= max_plies <= 10:
        raise ValueError("config: book.max_plies deve estar entre 0 e 10 (regra da competição)")

    known = {f.name for f in dataclasses.fields(TimeConfig)}
    time_data = data.get("time", {})
    unknown = set(time_data) - known
    if unknown:
        raise ValueError(f"config: chaves desconhecidas em [time]: {sorted(unknown)}")

    return Config(
        engine=engine,
        book_path=_resolve(base, book.get("path")),
        book_max_plies=max_plies,
        log_dir=_resolve(base, data.get("log", {}).get("dir", "logs")),
        ponder=bool(data.get("ponder", {}).get("enabled", True)),
        time=TimeConfig(**time_data),
    )
