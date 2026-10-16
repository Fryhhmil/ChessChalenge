import chess
import chess.engine

from chessbot.game_logger import GameLogger, MoveRecord, format_score


def test_format_score_white_pov():
    assert format_score(chess.engine.PovScore(chess.engine.Cp(35), chess.WHITE)) == "+0.35"
    assert format_score(chess.engine.PovScore(chess.engine.Cp(35), chess.BLACK)) == "-0.35"
    assert format_score(chess.engine.PovScore(chess.engine.Mate(3), chess.BLACK)) == "#-3"
    assert format_score(None) == "-"


def test_log_file_has_required_fields(tmp_path):
    logger = GameLogger(tmp_path, chess.BLACK, header=["motor: teste"])
    logger.log_move(MoveRecord(1, chess.WHITE, "e2e4", "adversario", 12.3))
    logger.log_move(MoveRecord(
        1, chess.BLACK, "c7c5", "motor", 8.0, depth=24, seldepth=31, nodes=123456,
        score=chess.engine.PovScore(chess.engine.Cp(-20), chess.BLACK),
        pv=[chess.Move.from_uci(m) for m in ("c7c5", "g1f3", "d7d6")]))
    logger.close()

    assert logger.path.name.endswith("_pretas.log")
    lines = logger.path.read_text(encoding="utf-8").splitlines()
    assert any("motor: teste" in line for line in lines)
    assert "lance | cor | uci | prof | nos | aval | tempo_s | origem | pv" in lines
    assert lines[-2] == "1 | brancas | e2e4 | - | - | - | 12.30 | adversario | -"
    assert lines[-1] == "1 | pretas | c7c5 | 24/31 | 123456 | +0.20 | 8.00 | motor | c7c5 g1f3 d7d6"


def test_one_file_per_game(tmp_path):
    a = GameLogger(tmp_path, chess.WHITE)
    b = GameLogger(tmp_path, chess.WHITE)
    a.close(), b.close()
    assert a.path != b.path
    assert len(list(tmp_path.glob("*.log"))) == 2
