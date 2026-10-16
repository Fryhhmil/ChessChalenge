import struct

import chess
import chess.polyglot
import pytest

from chessbot.book import OpeningBook

# Linha principal da Ruy Lopez: 12 meios-lances, todos no book de teste.
LINE = ["e2e4", "e7e5", "g1f3", "b8c6", "f1b5", "a7a6",
        "b5a4", "g8f6", "d2d3", "f8c5", "c2c3", "d7d6"]


def encode(move: chess.Move) -> int:
    value = (chess.square_file(move.to_square)
             | chess.square_rank(move.to_square) << 3
             | chess.square_file(move.from_square) << 6
             | chess.square_rank(move.from_square) << 9)
    if move.promotion:
        value |= (move.promotion - 1) << 12
    return value


@pytest.fixture
def book_path(tmp_path):
    entries = []
    board = chess.Board()
    for uci in LINE:
        move = chess.Move.from_uci(uci)
        entries.append((chess.polyglot.zobrist_hash(board), encode(move), 100))
        board.push(move)
    entries.sort()
    path = tmp_path / "test.bin"
    path.write_bytes(b"".join(struct.pack(">QHHI", k, m, w, 0) for k, m, w in entries))
    return path


def play(n):
    board = chess.Board()
    for uci in LINE[:n]:
        board.push_uci(uci)
    return board


@pytest.mark.parametrize("plies", range(10))
def test_book_used_before_limit(book_path, plies):
    book = OpeningBook(book_path, max_plies=10)
    assert book.pick(play(plies)) == chess.Move.from_uci(LINE[plies])


@pytest.mark.parametrize("plies", [10, 11])
def test_book_hard_cut_at_tenth_half_move(book_path, plies):
    book = OpeningBook(book_path, max_plies=10)
    board = play(plies)
    assert not book.is_allowed(board)
    assert book.pick(board) is None


def test_fen_resync_keeps_limit(book_path):
    """Um FEN da mesma posição (sem histórico) continua contando os meios-lances."""
    book = OpeningBook(book_path, max_plies=10)
    board = chess.Board(play(10).fen())
    assert not board.move_stack
    assert board.ply() == 10
    assert book.pick(board) is None
    assert book.pick(chess.Board(play(9).fen())) == chess.Move.from_uci(LINE[9])


def test_undo_back_inside_limit_reenables_book(book_path):
    book = OpeningBook(book_path, max_plies=10)
    board = play(10)
    assert book.pick(board) is None
    board.pop()
    assert book.pick(board) == chess.Move.from_uci(LINE[9])


def test_custom_limit(book_path):
    book = OpeningBook(book_path, max_plies=4)
    assert book.pick(play(3)) is not None
    assert book.pick(play(4)) is None


def test_position_not_in_book(book_path):
    board = chess.Board()
    board.push_uci("a2a3")
    assert OpeningBook(book_path).pick(board) is None


def test_missing_or_empty_book_is_disabled(tmp_path):
    empty = tmp_path / "empty.bin"
    empty.write_bytes(b"")
    for book in (OpeningBook(tmp_path / "nope.bin"), OpeningBook(empty), OpeningBook(None)):
        assert not book.available
        assert book.pick(chess.Board()) is None
    assert "vazio" in OpeningBook(empty).status
