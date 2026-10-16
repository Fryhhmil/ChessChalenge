import chess
import pytest

from chessbot.time_manager import (
    MATE_SCORE, ClockTracker, IterationInfo, Phase, StopController, TimeBudget, TimeConfig,
    allocate, classify_phase, format_clock, non_pawn_material, parse_clock,
)

CFG = TimeConfig()
NORMAL_PHASES = [Phase.OPENING, Phase.MIDDLEGAME, Phase.ENDGAME]


# ---------------------------------------------------------------- fases

def test_start_position_is_opening():
    assert classify_phase(chess.Board(), CFG) is Phase.OPENING


def test_middlegame_after_opening_plies():
    board = chess.Board()
    board.set_fen("r1bq1rk1/pp2bppp/2n1pn2/3p4/3P4/2NBPN2/PP3PPP/R2QK2R w KQ - 0 15")
    assert classify_phase(board, CFG) is Phase.MIDDLEGAME


def test_endgame_by_material():
    board = chess.Board("8/5pk1/6p1/8/3R4/6P1/r4PK1/8 w - - 0 40")
    assert non_pawn_material(board) == 10
    assert classify_phase(board, CFG) is Phase.ENDGAME


def test_tablebase_only_when_enabled():
    board = chess.Board("8/8/4k3/8/8/3KP3/8/8 w - - 0 60")  # 3 peças
    assert classify_phase(board, CFG, tablebase_pieces=5) is Phase.TABLEBASE
    assert classify_phase(board, CFG, tablebase_pieces=0) is Phase.ENDGAME


def test_six_pieces_is_not_tablebase_with_limit_5():
    board = chess.Board("8/8/4k3/2p5/8/3KP3/1P6/8 w - - 0 60")  # 5? K,k,p,P,P = 5
    assert classify_phase(board, CFG, tablebase_pieces=5) is Phase.TABLEBASE
    board6 = chess.Board("8/8/4k3/2p5/8/3KP3/1P4p1/8 w - - 0 60")  # 6 peças
    assert classify_phase(board6, CFG, tablebase_pieces=5) is not Phase.TABLEBASE


# ---------------------------------------------------------------- orçamento

@pytest.mark.parametrize("phase", NORMAL_PHASES)
@pytest.mark.parametrize("remaining", [900, 600, 300, 120, 61, 59, 30, 15, 11, 5, 0.5, 0])
def test_budget_is_ordered_and_under_hard_cap(phase, remaining):
    b = allocate(remaining, phase, CFG)
    assert 0 < b.minimum <= b.target <= b.maximum
    hard_cap = max(CFG.absolute_min_s, remaining - CFG.human_overhead_s - CFG.hard_safety_s)
    assert b.maximum <= hard_cap + 1e-9


@pytest.mark.parametrize("phase", NORMAL_PHASES)
def test_budget_monotonic_in_remaining_time(phase):
    previous = None
    for remaining in range(0, 1801, 3):
        b = allocate(remaining, phase, CFG)
        if previous is not None:
            assert b.target >= previous.target - 1e-9, remaining
            assert b.maximum >= previous.maximum - 1e-9, remaining
        previous = b


def test_full_clock_budget_is_reasonable():
    b = allocate(900, Phase.MIDDLEGAME, CFG)
    # (900-30)*1.15/32 ≈ 31 s; incremento líquido 0
    assert 25 < b.target < 35
    assert b.maximum <= 900 * CFG.max_fraction


def test_overhead_reduces_budget():
    with_overhead = allocate(600, Phase.MIDDLEGAME, TimeConfig(human_overhead_s=10))
    without = allocate(600, Phase.MIDDLEGAME, TimeConfig(human_overhead_s=0))
    assert with_overhead.target == pytest.approx(without.target - 10)


def test_increment_increases_budget():
    low = allocate(600, Phase.MIDDLEGAME, CFG, increment_s=10)
    high = allocate(600, Phase.MIDDLEGAME, CFG, increment_s=20)
    assert high.target > low.target


def test_middlegame_gets_more_than_opening():
    assert allocate(700, Phase.MIDDLEGAME, CFG).target > allocate(700, Phase.OPENING, CFG).target


def test_emergency_mode_below_threshold():
    b = allocate(CFG.emergency_s - 1, Phase.MIDDLEGAME, CFG)
    assert b.emergency
    assert b.minimum == CFG.absolute_min_s
    assert b.maximum <= b.target * 1.5 + 1e-9
    assert not allocate(CFG.emergency_s + 1, Phase.MIDDLEGAME, CFG).emergency


def test_emergency_never_thinks_longer_than_clock():
    for remaining in [20, 12, 10, 5, 1, 0]:
        b = allocate(remaining, Phase.ENDGAME, CFG)
        assert b.maximum <= max(CFG.absolute_min_s, remaining)


def test_tablebase_is_fast():
    b = allocate(600, Phase.TABLEBASE, CFG)
    assert b.target == CFG.tablebase_move_s
    assert b.maximum <= 2 * CFG.tablebase_move_s
    assert not b.emergency


def test_negative_net_increment_reserves_future_overhead():
    cfg = TimeConfig(human_overhead_s=15, increment_s=10)
    b = allocate(600, Phase.MIDDLEGAME, cfg)
    assert b.target == pytest.approx(1.15 * 570 / 32 - 5)


# ---------------------------------------------------------------- parada dinâmica

def budget(target=10.0, minimum=1.0, maximum=30.0):
    return TimeBudget(minimum, target, maximum, Phase.MIDDLEGAME)


def feed(ctl, moves, scores=None, start_depth=1):
    scores = scores or [30] * len(moves)
    for i, (move, score) in enumerate(zip(moves, scores)):
        ctl.update(IterationInfo(depth=start_depth + i, best_move=move, score_cp=score))


def test_no_info_uses_target():
    ctl = StopController(budget(), CFG)
    assert not ctl.should_stop(9.9)
    assert ctl.should_stop(10.0)


def test_never_stops_before_minimum():
    ctl = StopController(budget(minimum=2.0), CFG)
    feed(ctl, ["e2e4"] * 25)
    assert not ctl.should_stop(1.9)


def test_always_stops_at_maximum():
    ctl = StopController(budget(), CFG)
    feed(ctl, ["e2e4", "d2d4"] * 10, scores=[0, -300] * 10)
    assert ctl.should_stop(30.0)


def test_stable_best_move_stops_early():
    ctl = StopController(budget(), CFG)
    feed(ctl, ["e2e4"] * 20)
    assert ctl.time_limit() == pytest.approx(10.0 * CFG.stable_factor)
    assert ctl.should_stop(5.0)


def test_shallow_depth_is_not_trusted():
    ctl = StopController(budget(), CFG)
    feed(ctl, ["e2e4"] * (CFG.min_depth - 1))
    assert ctl.time_limit() == pytest.approx(10.0)


def test_best_move_change_extends():
    ctl = StopController(budget(), CFG)
    feed(ctl, ["e2e4"] * 15 + ["d2d4"])
    assert ctl.time_limit() == pytest.approx(10.0 * CFG.unstable_factor)
    assert not ctl.should_stop(12.0)


def test_eval_drop_extends_time():
    stable = StopController(budget(), CFG)
    feed(stable, ["e2e4"] * 20)
    dropping = StopController(budget(), CFG)
    feed(dropping, ["e2e4"] * 20, scores=[50] * 19 + [-30])
    assert dropping.eval_drop() == 80
    assert dropping.time_limit() > 10.0 > stable.time_limit()


def test_eval_drop_relative_to_previous_move():
    ctl = StopController(budget(), CFG, reference_cp=120)
    feed(ctl, ["e2e4"] * 20, scores=[40] * 20)
    assert ctl.eval_drop() == 80
    assert ctl.time_limit() > 10.0


def test_eval_drop_extension_is_capped_by_maximum():
    ctl = StopController(budget(maximum=15.0), CFG)
    feed(ctl, ["e2e4"] * 20, scores=[500] * 19 + [-500])
    assert ctl.time_limit() == pytest.approx(15.0)


def test_eval_rise_does_not_extend():
    ctl = StopController(budget(), CFG)
    feed(ctl, ["e2e4"] * 20, scores=list(range(0, 200, 10)))
    assert ctl.time_limit() < 10.0


def test_found_mate_stops_early():
    ctl = StopController(budget(), CFG)
    feed(ctl, ["h5f7"] * 12, scores=[MATE_SCORE - 3] * 12)
    assert ctl.time_limit() <= 10.0 * CFG.stable_factor


def test_same_depth_pv_update_with_new_move_resets_stability():
    ctl = StopController(budget(), CFG)
    feed(ctl, ["e2e4"] * 15)
    ctl.update(IterationInfo(depth=15, best_move="g1f3", score_cp=30))
    assert ctl.stable_count == 0
    assert ctl.time_limit() > 10.0


# ---------------------------------------------------------------- relógio

def test_clock_tracker():
    clock = ClockTracker(mine=900, opponent=900, increment_s=10, overhead_s=10)
    clock.my_move_done(think_s=20)
    assert clock.mine == pytest.approx(880)
    clock.opponent_move_done(elapsed_s=35)
    assert clock.opponent == pytest.approx(875)
    clock.sync(500, 400)
    assert (clock.mine, clock.opponent) == (500, 400)


@pytest.mark.parametrize("text, seconds", [("754", 754), ("12:34", 754), ("1:00:00", 3600), ("0:05.5", 5.5)])
def test_parse_clock(text, seconds):
    assert parse_clock(text) == pytest.approx(seconds)


@pytest.mark.parametrize("text", ["", "a:10", "1::2", "-5", "1:2:3:4"])
def test_parse_clock_rejects_garbage(text):
    with pytest.raises(ValueError):
        parse_clock(text)


def test_format_clock():
    assert format_clock(754) == "12:34"
    assert format_clock(-3) == "0:00"
