"""
Controlador da partida: estado oficial (python-chess), comandos do operador,
relógio estimado, ponder e log. Não depende de Qt: a GUI só chama
``handle()``, roda ``think()`` numa thread e devolve o resultado em
``finish_think()`` na thread principal.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Callable, Optional

import chess

from .book import OpeningBook
from .commands import HELP, Command, CommandError, parse_command
from .config import Config
from .engine import Engine, SearchSession
from .game_logger import GameLogger, MoveRecord
from .search import InfoCallback, SearchResult, Searcher
from .time_manager import ClockTracker, format_clock


def color_name(color: chess.Color) -> str:
    return "brancas" if color == chess.WHITE else "pretas"


@dataclass
class Response:
    message: str
    think: bool = False          # a GUI deve iniciar think() em background
    ok: bool = True


class GameController:
    def __init__(self, cfg: Config, engine: Engine, book: OpeningBook,
                 clock: Callable[[], float] = time.monotonic,
                 logger_factory: Callable[..., GameLogger] = GameLogger):
        self.cfg = cfg
        self.engine = engine
        self.book = book
        self.clock = clock
        self.logger_factory = logger_factory
        self.searcher = Searcher(engine, book, cfg.time, clock=clock)

        self.board = chess.Board()
        self.my_color: Optional[chess.Color] = None
        self.clocks = self._fresh_clocks()
        self.logger: Optional[GameLogger] = None
        self.thinking = False
        self.force = threading.Event()
        self.last_result: Optional[SearchResult] = None
        self._game_token: object = object()
        self._ponder: Optional[SearchSession] = None
        self._ponder_move: Optional[chess.Move] = None
        self._my_turn_started: Optional[float] = None
        self._opp_turn_started: Optional[float] = None
        self._last_eval_cp: Optional[int] = None

    # ------------------------------------------------------------ estado

    def _fresh_clocks(self) -> ClockTracker:
        t = self.cfg.time
        return ClockTracker(t.initial_s, t.initial_s, t.increment_s, t.human_overhead_s)

    @property
    def in_game(self) -> bool:
        return self.my_color is not None

    @property
    def my_turn(self) -> bool:
        return self.in_game and self.board.turn == self.my_color and not self.board.is_game_over()

    def live_clocks(self) -> tuple[float, float]:
        """Relógios estimados agora (descontando o turno em andamento)."""
        now = self.clock()
        mine, opp = self.clocks.mine, self.clocks.opponent
        if self.my_turn and self._my_turn_started is not None:
            mine -= now - self._my_turn_started
        elif self.in_game and self._opp_turn_started is not None and not self.board.is_game_over():
            opp -= now - self._opp_turn_started
        return max(0.0, mine), max(0.0, opp)

    def clock_text(self) -> str:
        mine, opp = self.live_clocks()
        return f"Nós {format_clock(mine)}  |  Adversário {format_clock(opp)}"

    # ------------------------------------------------------------ comandos

    def handle(self, text: str) -> Response:
        try:
            cmd = parse_command(text)
        except CommandError as exc:
            return Response(str(exc), ok=False)

        if self.thinking and cmd.kind not in ("now", "clock", "help"):
            return Response("motor pensando: use 'now' para forçar o lance", ok=False)

        if cmd.kind == "help":
            return Response(HELP)
        if cmd.kind == "new":
            return self.new_game(cmd.color)
        if not self.in_game:
            return Response("nenhuma partida: use 'new white' ou 'new black'", ok=False)

        handler = {
            "move": self._cmd_move, "undo": self._cmd_undo, "fen": self._cmd_fen,
            "clock": self._cmd_clock, "go": self._cmd_go, "now": self._cmd_now,
        }[cmd.kind]
        return handler(cmd)

    def new_game(self, color: chess.Color) -> Response:
        self._stop_ponder()
        if self.logger is not None:
            self.logger.note("partida encerrada (nova partida iniciada)")
            self.logger.close()
        self.board = chess.Board()
        self.my_color = color
        self.clocks = self._fresh_clocks()
        self._game_token = object()
        self._last_eval_cp = None
        self.last_result = None
        now = self.clock()
        self._my_turn_started = now if color == chess.WHITE else None
        self._opp_turn_started = now if color == chess.BLACK else None
        t = self.cfg.time
        header = [*self.engine.describe(), self.book.status,
                  f"book: limite de {self.book.max_plies} meios-lances",
                  f"tablebase: até {self.engine.tablebase_pieces} peças",
                  f"relógio: {t.initial_s:.0f}s + {t.increment_s:.0f}s; overhead humano {t.human_overhead_s:.0f}s",
                  f"ponder: {'ligado' if self.cfg.ponder else 'desligado'}"]
        self.logger = self.logger_factory(self.cfg.log_dir, color, header)
        return Response(f"nova partida: motor joga de {color_name(color)}", think=color == chess.WHITE)

    def _cmd_move(self, cmd: Command) -> Response:
        move = cmd.move
        if self.board.is_game_over():
            return Response("a partida já terminou", ok=False)
        if self.my_turn:
            return Response("é a vez do NOSSO motor; para corrigir use undo/fen", ok=False)
        if move not in self.board.legal_moves:
            # e7e8 sem promoção: dica útil
            if chess.Move(move.from_square, move.to_square, chess.QUEEN) in self.board.legal_moves:
                return Response(f"lance ilegal: {move.uci()} (promoção? ex.: {move.uci()}q)", ok=False)
            return Response(f"lance ilegal: {move.uci()}", ok=False)

        now = self.clock()
        elapsed = now - self._opp_turn_started if self._opp_turn_started is not None else 0.0
        self.clocks.opponent_move_done(elapsed)
        self._log_move(move, "adversario", elapsed)
        self.board.push(move)
        self._my_turn_started = now
        self._opp_turn_started = None
        if self._game_over_note():
            self._stop_ponder()
            return Response(f"adversário: {move.uci()} — fim de jogo: {self.board.result()}")
        return Response(f"adversário: {move.uci()}", think=True)

    def _cmd_undo(self, cmd: Command) -> Response:
        if not self.board.move_stack:
            return Response("nada para desfazer", ok=False)
        self._stop_ponder()
        move = self.board.pop()
        self.logger.note(f"undo: {move.uci()} desfeito; FEN {self.board.fen()}")
        self._turn_timers_reset()
        hint = " — vez do motor: digite 'go'" if self.my_turn else ""
        return Response(f"desfeito: {move.uci()}{hint}")

    def _cmd_fen(self, cmd: Command) -> Response:
        board = chess.Board(cmd.fen)
        if not board.is_valid():
            return Response(f"posição inválida: {board.status()!r}", ok=False)
        self._stop_ponder()
        self.board = board
        self.logger.note(f"fen: tabuleiro ressincronizado para {board.fen()}")
        self._turn_timers_reset()
        hint = " — vez do motor: digite 'go'" if self.my_turn else ""
        return Response(f"tabuleiro ressincronizado{hint}")

    def _cmd_clock(self, cmd: Command) -> Response:
        self.clocks.sync(cmd.mine, cmd.opponent)
        now = self.clock()
        # O valor digitado é o relógio físico AGORA: reinicia a contagem do turno.
        if self.my_turn and self._my_turn_started is not None:
            # O tempo já pensado neste lance não é descontado de novo.
            self.clocks.mine += now - self._my_turn_started
        elif self._opp_turn_started is not None:
            self._opp_turn_started = now
        self.logger.note(f"clock: nós {format_clock(cmd.mine)}, adversário {format_clock(cmd.opponent)}")
        return Response(f"relógios sincronizados: {self.clock_text()}")

    def _cmd_go(self, cmd: Command) -> Response:
        if not self.my_turn:
            return Response("não é a vez do motor", ok=False)
        if self._my_turn_started is None:
            self._my_turn_started = self.clock()
        return Response("motor pensando", think=True)

    def _cmd_now(self, cmd: Command) -> Response:
        if not self.thinking:
            return Response("o motor não está pensando", ok=False)
        self.force.set()
        return Response("forçando o lance")

    def _turn_timers_reset(self) -> None:
        now = self.clock()
        if self.my_turn:
            self._my_turn_started, self._opp_turn_started = now, None
        else:
            self._my_turn_started, self._opp_turn_started = None, now

    # ------------------------------------------------------------ busca

    def prepare_think(self) -> Optional[SearchSession]:
        """
        Chamado na thread principal antes de ``think``. Marca o motor como
        pensando e devolve a sessão de ponder se o adversário jogou o lance
        previsto (senão a descarta).
        """
        if not self.my_turn:
            raise RuntimeError("não é a vez do motor")
        self.thinking = True
        self.force.clear()
        if self._my_turn_started is None:
            self._my_turn_started = self.clock()
        session = None
        if self._ponder is not None:
            if (self.board.move_stack and self._ponder.root.fen() == self.board.fen()
                    and self._ponder_move == self.board.peek()):
                session = self._ponder
                self._ponder = None
            else:
                self._stop_ponder()
        return session

    def think(self, session: Optional[SearchSession] = None,
              on_info: Optional[InfoCallback] = None) -> SearchResult:
        """Bloqueante; pode rodar em outra thread (não altera o estado do jogo)."""
        remaining, _ = self.live_clocks()
        return self.searcher.choose(
            self.board.copy(), remaining, session=session, reference_cp=self._last_eval_cp,
            force=self.force, on_info=on_info, game=self._game_token)

    def finish_think(self, result: SearchResult) -> Response:
        """Aplica o lance escolhido (thread principal), registra no log e inicia o ponder."""
        self.thinking = False
        now = self.clock()
        think_s = now - self._my_turn_started if self._my_turn_started is not None else result.elapsed
        if result.budget is not None:
            self.logger.note(f"orçamento {result.budget}; relógio no início do lance "
                             f"{format_clock(self.clocks.mine)}; parou em {result.elapsed:.2f}s")
        self.clocks.my_move_done(think_s)
        self._log_move(result.move, result.source, think_s, result)
        if result.score_cp is not None:
            self._last_eval_cp = result.score_cp
        self.board.push(result.move)
        self.last_result = result
        self._my_turn_started = None
        self._opp_turn_started = now
        if self._game_over_note():
            return Response(f"MOTOR JOGA {result.move.uci()} — fim de jogo: {self.board.result()}")
        self._start_ponder(result)
        return Response(f"MOTOR JOGA {result.move.uci()}")

    def abort_think(self, error: Exception) -> Response:
        self.thinking = False
        if self.logger:
            self.logger.note(f"ERRO na busca: {error!r}")
        return Response(f"erro na busca: {error}", ok=False)

    # ------------------------------------------------------------ ponder

    def _start_ponder(self, result: SearchResult) -> None:
        if not self.cfg.ponder or self.board.is_game_over():
            return
        board = self.board.copy()
        predicted = result.pv[1] if len(result.pv) > 1 else None
        if predicted is not None and predicted in board.legal_moves:
            board.push(predicted)
            if board.is_game_over():
                return
        else:
            predicted = None  # sem previsão: analisa a posição do adversário (aquece a hash)
        self._ponder_move = predicted
        self._ponder = self.engine.start(board, game=self._game_token)

    def _stop_ponder(self) -> None:
        if self._ponder is not None:
            self._ponder.stop()
            self._ponder = None
            self._ponder_move = None

    @property
    def ponder_move(self) -> Optional[chess.Move]:
        return self._ponder_move if self._ponder is not None else None

    # ------------------------------------------------------------ log

    def _log_move(self, move: chess.Move, source: str, time_s: float,
                  result: Optional[SearchResult] = None) -> None:
        record = MoveRecord(self.board.fullmove_number, self.board.turn, move.uci(), source, time_s)
        if result is not None:
            record.depth, record.seldepth, record.nodes = result.depth, result.seldepth, result.nodes
            record.score, record.pv = result.score, result.pv
        self.logger.log_move(record)

    def _game_over_note(self) -> bool:
        if not self.board.is_game_over():
            return False
        outcome = self.board.outcome()
        self.logger.note(f"fim de jogo: {self.board.result()} ({outcome.termination.name})")
        return True

    def close(self) -> None:
        self._stop_ponder()
        if self.logger is not None:
            self.logger.close()
