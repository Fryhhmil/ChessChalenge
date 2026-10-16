"""
Escolha do lance: book → lance único → busca ``go infinite`` com parada
decidida pelo ``time_manager``.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

import chess
import chess.engine

from .book import OpeningBook
from .engine import Engine, SearchSession
from .time_manager import (
    StopController, TimeBudget, TimeConfig, allocate, classify_phase,
)


@dataclass
class SearchResult:
    move: chess.Move
    source: str                          # book, forcado, motor, ponder-hit
    elapsed: float
    budget: Optional[TimeBudget] = None
    depth: Optional[int] = None
    seldepth: Optional[int] = None
    nodes: Optional[int] = None
    score: Optional[chess.engine.PovScore] = None
    pv: list[chess.Move] = field(default_factory=list)
    score_cp: Optional[int] = None       # do nosso ponto de vista (referência p/ próximo lance)


InfoCallback = Callable[[dict, StopController, float], None]


class Searcher:
    def __init__(self, engine: Engine, book: OpeningBook, tcfg: TimeConfig,
                 clock: Callable[[], float] = time.monotonic, poll_interval: float = 0.01):
        self.engine = engine
        self.book = book
        self.tcfg = tcfg
        self.clock = clock
        self.poll_interval = poll_interval

    def choose(self, board: chess.Board, remaining_s: float, *,
               session: Optional[SearchSession] = None,
               reference_cp: Optional[int] = None,
               force: Optional[threading.Event] = None,
               on_info: Optional[InfoCallback] = None,
               game: object = None) -> SearchResult:
        """
        Decide o lance para ``board``. ``session`` é uma busca de ponder já
        rodando exatamente nesta posição (acerto de ponder), que é reaproveitada.
        """
        start = self.clock()
        legal = list(board.legal_moves)
        if not legal:
            raise ValueError("posição sem lances legais")

        book_move = self.book.pick(board)
        if book_move is not None or len(legal) == 1:
            if session is not None:
                session.stop()
            move = book_move or legal[0]
            return SearchResult(move, "book" if book_move else "forcado", self.clock() - start)

        phase = classify_phase(board, self.tcfg, self.engine.tablebase_pieces)
        budget = allocate(remaining_s, phase, self.tcfg)
        ctl = StopController(budget, self.tcfg, reference_cp=reference_cp)

        reused = session is not None
        if session is None:
            session = self.engine.start(board, game=game)
        else:
            session.poll()
            for info in session.lines:
                ctl.update(session.iteration(info))

        while True:
            for info in session.poll():
                ctl.update(session.iteration(info))
                if on_info is not None:
                    on_info(info, ctl, self.clock() - start)
            elapsed = self.clock() - start
            forced = force is not None and force.is_set()
            if session.finished or ctl.should_stop(elapsed) or (forced and session.lines):
                break
            time.sleep(self.poll_interval)

        bestmove = session.stop()
        line = session.best_line
        elapsed = self.clock() - start
        move = bestmove or (line["pv"][0] if line else legal[0])

        result = SearchResult(move, "ponder-hit" if reused else "motor", elapsed, budget)
        if line is not None:
            result.pv = list(line["pv"]) if line["pv"][0] == move else [move]
            result.depth = line.get("depth")
            result.seldepth = line.get("seldepth")
            result.score = line.get("score")
            result.score_cp = session.iteration(line).score_cp
        result.nodes = session.latest.get("nodes")
        return result
