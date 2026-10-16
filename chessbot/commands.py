"""
Parser dos comandos digitados pelo operador.

Formatos aceitos::

    e2e4 | e7e8q          lance em UCI (legalidade é checada pelo GameController)
    undo                  desfaz o último meio-lance
    fen <FEN>             ressincroniza com o tabuleiro físico
    clock <meu> <adv>     sincroniza relógios (segundos, mm:ss ou h:mm:ss)
    new white|black       nova partida com o motor jogando com essa cor
    go                    manda o motor pensar (se for a vez dele)
    now                   força o motor a jogar imediatamente
    help                  lista os comandos
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

import chess

from .time_manager import parse_clock

_MOVE_RE = re.compile(r"^[a-h][1-8][a-h][1-8][qrbn]?$")
_COLORS = {"white": chess.WHITE, "w": chess.WHITE, "brancas": chess.WHITE, "b": chess.BLACK,
           "black": chess.BLACK, "pretas": chess.BLACK}

HELP = ("Comandos: <lance UCI> (e2e4, e7e8q) | undo | fen <FEN> | clock <meu> <adv> "
        "| new white|black | go | now | help")


class CommandError(ValueError):
    pass


@dataclass(frozen=True)
class Command:
    kind: str                      # move, undo, fen, clock, new, go, now, help
    move: Optional[chess.Move] = None
    fen: Optional[str] = None
    mine: Optional[float] = None
    opponent: Optional[float] = None
    color: Optional[chess.Color] = None


def parse_command(text: str) -> Command:
    text = text.strip()
    if not text:
        raise CommandError("entrada vazia")
    head, _, rest = text.partition(" ")
    head = head.lower()
    rest = rest.strip()

    if _MOVE_RE.match(head) and not rest:
        return Command("move", move=chess.Move.from_uci(head))
    if head in ("undo", "go", "now", "help") and not rest:
        return Command(head)
    if head == "fen":
        if not rest:
            raise CommandError("uso: fen <FEN>")
        try:
            chess.Board(rest)
        except ValueError as exc:
            raise CommandError(f"FEN inválido: {exc}") from exc
        return Command("fen", fen=rest)
    if head == "clock":
        parts = rest.split()
        if len(parts) != 2:
            raise CommandError("uso: clock <meu_tempo> <tempo_adv>  (ex.: clock 12:34 11:02)")
        try:
            return Command("clock", mine=parse_clock(parts[0]), opponent=parse_clock(parts[1]))
        except ValueError as exc:
            raise CommandError(str(exc)) from exc
    if head == "new":
        color = _COLORS.get(rest.lower())
        if color is None:
            raise CommandError("uso: new white|black  (cor do NOSSO motor)")
        return Command("new", color=color)
    raise CommandError(f"comando ou lance inválido: {text!r}. {HELP}")
