"""
Opening book Polyglot com o limite RÍGIDO da competição.

O book só pode ser consultado enquanto a partida tiver menos de ``max_plies``
meios-lances jogados (contados desde a posição inicial). A contagem usa
``board.ply()``, que também funciona depois de um ``fen`` (deriva do número do
lance e de quem joga), então ressincronizar o tabuleiro não "reabre" o book.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import chess
import chess.polyglot

log = logging.getLogger(__name__)


class OpeningBook:
    def __init__(self, path: Optional[Path], max_plies: int = 10):
        self.max_plies = max_plies
        self.path = Path(path) if path else None
        self._reader: Optional[chess.polyglot.MemoryMappedReader] = None
        self.status = self._open()

    def _open(self) -> str:
        if self.path is None:
            return "book desativado"
        if not self.path.is_file():
            return f"book não encontrado: {self.path}"
        if self.path.stat().st_size == 0:
            return f"book vazio (0 bytes): {self.path}"
        try:
            self._reader = chess.polyglot.open_reader(self.path)
        except (OSError, ValueError) as exc:
            return f"erro ao abrir book {self.path}: {exc}"
        return f"book: {self.path.name}"

    @property
    def available(self) -> bool:
        return self._reader is not None

    def is_allowed(self, board: chess.Board) -> bool:
        """Verdadeiro só antes do limite de meios-lances (independe de haver book)."""
        return board.ply() < self.max_plies

    def pick(self, board: chess.Board) -> Optional[chess.Move]:
        """Lance de maior peso do book, ou ``None`` (fora do book ou após o limite)."""
        if self._reader is None or not self.is_allowed(board):
            return None
        try:
            entry = self._reader.find(board)
        except IndexError:
            return None
        except Exception as exc:  # arquivo corrompido não pode derrubar a partida
            log.warning("falha ao ler o book: %s", exc)
            return None
        return entry.move if entry.move in board.legal_moves else None

    def close(self) -> None:
        if self._reader is not None:
            self._reader.close()
            self._reader = None
