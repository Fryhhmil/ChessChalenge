"""
Wrapper do Stockfish via UCI (python-chess).

Toda busca é ``go infinite``: o processo nunca recebe ``wtime/btime``. Quem
decide a hora do ``stop`` é o ``Searcher`` com o ``time_manager``.
"""

from __future__ import annotations

import logging
from typing import Optional

import chess
import chess.engine

from .config import EngineConfig
from .time_manager import MATE_SCORE, IterationInfo

log = logging.getLogger(__name__)


class SearchSession:
    """
    Uma busca ``go infinite`` em andamento sobre ``root``.

    As linhas ``info`` ficam enfileiradas pelo python-chess; ``poll()`` as
    consome sem bloquear. Assim uma sessão de ponder pode rodar sem thread
    própria e, num acerto, ser "adotada" pela busca do nosso lance com todo o
    histórico de iterações.
    """

    def __init__(self, analysis: chess.engine.SimpleAnalysisResult, root: chess.Board):
        self._analysis = analysis
        self.root = root
        self.lines: list[dict] = []        # infos completas (com pv e score, sem bound)
        self.latest: dict = {}             # última info de qualquer tipo (nós, tempo...)
        self.finished = False
        self.bestmove: Optional[chess.Move] = None

    def poll(self) -> list[dict]:
        """Consome as infos disponíveis sem bloquear; devolve as novas linhas completas."""
        new = []
        while not self.finished and not self._analysis.would_block():
            try:
                info = self._analysis.get()
            except chess.engine.AnalysisComplete:
                self.finished = True
                break
            self.latest = {**self.latest, **info}
            if ("pv" in info and info["pv"] and "score" in info and "depth" in info
                    and not info.get("lowerbound") and not info.get("upperbound")):
                self.lines.append(info)
                new.append(info)
        return new

    def iteration(self, info: dict) -> IterationInfo:
        score = info["score"].pov(self.root.turn).score(mate_score=MATE_SCORE)
        return IterationInfo(depth=info["depth"], best_move=info["pv"][0].uci(), score_cp=score)

    @property
    def best_line(self) -> Optional[dict]:
        return self.lines[-1] if self.lines else None

    def stop(self) -> Optional[chess.Move]:
        """Manda ``stop``, espera o ``bestmove`` e drena as infos finais."""
        if self.finished and self.bestmove is not None:
            return self.bestmove
        self._analysis.stop()
        try:
            best = self._analysis.wait()
            self.bestmove = best.move
        except chess.engine.EngineError as exc:  # pragma: no cover
            log.warning("erro ao parar a busca: %s", exc)
        self.poll()
        self.finished = True
        return self.bestmove


class Engine:
    def __init__(self, cfg: EngineConfig):
        if not cfg.path.is_file():
            raise FileNotFoundError(f"Stockfish não encontrado: {cfg.path}")
        self.cfg = cfg
        self._engine = chess.engine.SimpleEngine.popen_uci(str(cfg.path))
        self.name = self._engine.id.get("name", "UCI engine")

        options = {"Threads": cfg.threads, "Hash": cfg.hash_mb}
        self.tablebase_pieces = 0
        tb = cfg.syzygy_path
        if tb and tb.is_dir() and any(tb.glob("*.rtbw")) and cfg.syzygy_probe_limit > 0:
            options["SyzygyPath"] = str(tb)
            options["SyzygyProbeLimit"] = cfg.syzygy_probe_limit
            self.tablebase_pieces = cfg.syzygy_probe_limit
        else:
            options["SyzygyProbeLimit"] = 0
        self._engine.configure({k: v for k, v in options.items() if k in self._engine.options})
        self.options = options

    def describe(self) -> list[str]:
        opts = ", ".join(f"{k}={v}" for k, v in self.options.items())
        return [f"motor: {self.name}", f"opções UCI: {opts}"]

    def start(self, board: chess.Board, game: object = None) -> SearchSession:
        """Inicia ``go infinite`` na posição (com histórico, para repetição)."""
        root = board.copy()
        analysis = self._engine.analysis(root, game=game)
        return SearchSession(analysis, root)

    def quit(self) -> None:
        try:
            self._engine.quit()
        except Exception:  # pragma: no cover
            self._engine.close()
