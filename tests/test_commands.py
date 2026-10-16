import chess
import pytest

from chessbot.commands import CommandError, parse_command


@pytest.mark.parametrize("text, uci", [("e2e4", "e2e4"), ("  E7E8Q ", "e7e8q"), ("g1f3", "g1f3")])
def test_moves(text, uci):
    cmd = parse_command(text)
    assert cmd.kind == "move" and cmd.move == chess.Move.from_uci(uci)


@pytest.mark.parametrize("text", ["", "e9e4", "e2e4x", "xyz", "e2", "e2e4 e7e5", "e7e8k", "0000"])
def test_bad_input(text):
    with pytest.raises(CommandError):
        parse_command(text)


def test_simple_commands():
    for kind in ("undo", "go", "now", "help"):
        assert parse_command(kind.upper()).kind == kind


def test_fen():
    fen = "8/8/4k3/8/8/3KP3/8/8 w - - 0 60"
    assert parse_command(f"fen {fen}").fen == fen
    with pytest.raises(CommandError):
        parse_command("fen isto nao e fen")
    with pytest.raises(CommandError):
        parse_command("fen")


def test_clock():
    cmd = parse_command("clock 12:34 600")
    assert (cmd.mine, cmd.opponent) == (754, 600)
    for bad in ("clock", "clock 10", "clock a b", "clock 1 2 3"):
        with pytest.raises(CommandError):
            parse_command(bad)


def test_new():
    assert parse_command("new white").color == chess.WHITE
    assert parse_command("new black").color == chess.BLACK
    with pytest.raises(CommandError):
        parse_command("new red")
