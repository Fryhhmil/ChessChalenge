"""
Log obrigatório da competição: um arquivo .log por partida.

Cada lance vira uma linha com: número do lance, cor, lance UCI, profundidade,
nós, avaliação, tempo gasto, origem e PV. A avaliação é sempre do ponto de
vista das BRANCAS (em peões, ``#n`` = mate em n). Os dados vêm das linhas
``info`` do UCI já parseadas pelo python-chess. O arquivo é gravado e
descarregado (flush) a cada linha, para sobreviver a um travamento.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Sequence

import chess
import chess.engine

COLUMNS = ("lance", "cor", "uci", "prof", "nos", "aval", "tempo_s", "origem", "pv")


def format_score(score: Optional[chess.engine.PovScore]) -> str:
    """Avaliação do ponto de vista das brancas: ``+0.35``, ``-1.20``, ``#3``, ``#-2``."""
    if score is None:
        return "-"
    white = score.white()
    mate = white.mate()
    if mate is not None:
        return f"#{mate}"
    return f"{white.score() / 100:+.2f}"


def format_nodes(nodes: Optional[int]) -> str:
    return "-" if nodes is None else str(nodes)


@dataclass
class MoveRecord:
    move_number: int
    color: chess.Color
    uci: str
    source: str                         # motor, book, forcado, ponder-hit, adversario
    time_s: float
    depth: Optional[int] = None
    seldepth: Optional[int] = None
    nodes: Optional[int] = None
    score: Optional[chess.engine.PovScore] = None
    pv: Sequence[chess.Move] = field(default_factory=list)

    def fields(self) -> list[str]:
        depth = "-" if self.depth is None else (
            f"{self.depth}/{self.seldepth}" if self.seldepth else str(self.depth))
        return [
            str(self.move_number),
            "brancas" if self.color == chess.WHITE else "pretas",
            self.uci,
            depth,
            format_nodes(self.nodes),
            format_score(self.score),
            f"{self.time_s:.2f}",
            self.source,
            " ".join(m.uci() for m in self.pv) or "-",
        ]


class GameLogger:
    def __init__(self, log_dir: Path, my_color: chess.Color, header: Sequence[str] = (),
                 now: Optional[dt.datetime] = None):
        now = now or dt.datetime.now()
        log_dir = Path(log_dir)
        log_dir.mkdir(parents=True, exist_ok=True)
        color = "brancas" if my_color == chess.WHITE else "pretas"
        base = f"partida_{now:%Y%m%d-%H%M%S}_{color}"
        path = log_dir / f"{base}.log"
        n = 1
        while path.exists():
            n += 1
            path = log_dir / f"{base}_{n}.log"
        self.path = path
        self._fh = open(path, "w", encoding="utf-8")
        self.note(f"Partida iniciada em {now:%Y-%m-%d %H:%M:%S}; nosso motor joga de {color}")
        for line in header:
            self.note(line)
        self.note("aval = ponto de vista das brancas (peões; #n = mate); prof = profundidade/seldepth")
        self._write(" | ".join(COLUMNS))

    def _write(self, line: str) -> None:
        self._fh.write(line + "\n")
        self._fh.flush()

    def note(self, text: str) -> None:
        stamp = dt.datetime.now().strftime("%H:%M:%S")
        self._write(f"# [{stamp}] {text}")

    def log_move(self, record: MoveRecord) -> None:
        self._write(" | ".join(record.fields()))

    def close(self) -> None:
        if not self._fh.closed:
            self._fh.close()
