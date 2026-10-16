"""
Testes com o Stockfish real (pulados se o binário não estiver em engines/).
Usam relógios curtos para rodar em poucos segundos.
"""

import logging
import random
from pathlib import Path

import chess
import pytest

from chessbot.book import OpeningBook
from chessbot.config import Config, EngineConfig, load_config
from chessbot.engine import Engine
from chessbot.game import GameController
from chessbot.time_manager import Phase, TimeConfig

ROOT = Path(__file__).resolve().parents[1]
REAL = load_config(ROOT / "config.toml")

pytestmark = pytest.mark.skipif(not REAL.engine.path.is_file(), reason="Stockfish não instalado")

FAST = TimeConfig(initial_s=40, increment_s=1, human_overhead_s=1, reserve_s=5,
                  min_move_s=0.05, emergency_s=10, min_depth=6, tablebase_move_s=0.1)


@pytest.fixture(scope="module")
def engine():
    eng = Engine(EngineConfig(path=REAL.engine.path, threads=2, hash_mb=32,
                              syzygy_path=REAL.engine.syzygy_path, syzygy_probe_limit=5))
    yield eng
    eng.quit()


def make_game(engine, tmp_path, book_path=None, ponder=True):
    cfg = Config(engine=engine.cfg, book_path=book_path, log_dir=tmp_path, ponder=ponder, time=FAST)
    return GameController(cfg, engine, OpeningBook(book_path, 10))


def engine_move(game):
    session = game.prepare_think()
    result = game.think(session)
    game.finish_think(result)
    return result


def test_options_respect_competition_rules(engine):
    assert engine.options["SyzygyProbeLimit"] == 5
    assert engine.tablebase_pieces in (0, 5)


def test_full_game_with_book_cut_and_log(engine, tmp_path, caplog):
    import struct
    import chess.polyglot
    from test_book import LINE, encode

    # Book que cobre 12 meios-lances: o motor só pode usá-lo até o 10º.
    entries, board = [], chess.Board()
    for uci in LINE:
        move = chess.Move.from_uci(uci)
        entries.append((chess.polyglot.zobrist_hash(board), encode(move), 1))
        board.push(move)
    book = tmp_path / "line.bin"
    book.write_bytes(b"".join(struct.pack(">QHHI", k, m, w, 0) for k, m, w in sorted(entries)))

    caplog.set_level(logging.DEBUG, logger="chess.engine")
    game = make_game(engine, tmp_path, book)
    assert game.handle("new white").think
    sources = []
    for ply in range(16):
        if game.board.turn == chess.WHITE:
            result = engine_move(game)
            sources.append((game.board.ply() - 1, result.source))
        else:
            # O "adversário" segue a linha do book enquanto der.
            uci = LINE[ply] if ply < len(LINE) else random.Random(ply).choice(list(game.board.legal_moves)).uci()
            assert game.handle(uci).ok
    game.close()

    book_plies = [ply for ply, src in sources if src == "book"]
    assert book_plies == [0, 2, 4, 6, 8]
    assert all(src != "book" for ply, src in sources if ply >= 10)

    sent = "\n".join(r.getMessage() for r in caplog.records)
    assert "go infinite" in sent
    for forbidden in ("wtime", "btime", "movetime", "winc"):
        assert forbidden not in sent

    lines = game.logger.path.read_text(encoding="utf-8").splitlines()
    moves = [line for line in lines if not line.startswith("#") and line[0].isdigit()]
    assert len(moves) == 16
    engine_lines = [line.split(" | ") for line in moves if " | motor | " in line or " | ponder-hit | " in line]
    assert engine_lines
    for cols in engine_lines:
        assert cols[3] != "-" and cols[4] != "-" and cols[5] != "-" and cols[8] != "-"


def test_ponder_hit_reuses_search(engine, tmp_path):
    game = make_game(engine, tmp_path)
    game.handle("new white")
    engine_move(game)
    predicted = game.ponder_move
    assert predicted is not None
    assert game.handle(predicted.uci()).think
    result = engine_move(game)
    assert result.source == "ponder-hit"
    game.close()


def test_ponder_miss_starts_fresh(engine, tmp_path):
    game = make_game(engine, tmp_path)
    game.handle("new white")
    engine_move(game)
    predicted = game.ponder_move
    other = next(m for m in game.board.legal_moves if m != predicted)
    game.handle(other.uci())
    assert engine_move(game).source == "motor"
    game.close()


def test_tablebase_endgame_is_fast(engine, tmp_path):
    if not engine.tablebase_pieces:
        pytest.skip("sem tablebases")
    game = make_game(engine, tmp_path, ponder=False)
    game.handle("new white")
    engine_move(game)
    game.handle("fen 8/8/8/4k3/8/8/4P3/R3K3 b - - 0 50")
    game.handle("e5e4")
    result = engine_move(game)
    assert result.budget.phase is Phase.TABLEBASE
    assert result.elapsed < 1.0
    game.close()


def test_commands_on_real_game(engine, tmp_path):
    game = make_game(engine, tmp_path, ponder=False)
    assert not game.handle("e2e4").ok                    # sem partida
    game.handle("new black")
    assert not game.handle("e2e5").ok                    # ilegal
    assert game.handle("e2e4").think
    engine_move(game)
    assert not game.handle("e2e4").ok                    # vez do adversário, lance ilegal
    assert game.handle("undo").ok                        # desfaz o lance do motor
    assert game.my_turn
    assert "go" in game.handle("undo").message or not game.my_turn
    assert game.board.ply() == 0
    r = game.handle("fen 4k3/P7/8/8/8/8/8/4K3 w - - 0 70")
    assert r.ok and not game.my_turn
    msg = game.handle("a7a8").message
    assert "promoção" in msg
    assert game.handle("clock 5:00 4:30").ok
    assert game.clocks.mine == 300
    game.close()
