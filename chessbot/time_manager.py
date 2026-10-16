"""
Gestão de tempo — componente decisório autoral do motor.

O Stockfish é usado apenas como "calculadora": ele roda com ``go infinite`` e
quem decide QUANTO tempo pensar e QUANDO parar é este módulo. Nada aqui usa o
gerenciamento interno do Stockfish (``go wtime/btime``).

O módulo é puro: não faz I/O, não lê relógio do sistema e não conhece o
processo UCI. Tudo entra como número (segundos, centipeões), o que o torna
determinístico e fácil de testar.

Visão geral
-----------
1. ``classify_phase`` decide a fase do jogo (abertura pós-book, meio-jogo,
   final, final coberto por tablebase).
2. ``allocate`` produz um ``TimeBudget`` (mínimo / alvo / máximo) para o lance
   a partir do tempo restante, do incremento e do overhead humano.
3. ``StopController`` recebe as iterações da busca e decide, a cada instante,
   se já é hora de mandar ``stop``: para cedo quando o melhor lance está
   estável e estende quando a avaliação cai ou o melhor lance muda.
4. ``ClockTracker`` mantém a estimativa do relógio físico entre
   sincronizações manuais (comando ``clock``).

O overhead humano
-----------------
Na competição o relógio que vale é o físico. Depois que o adversário aperta o
relógio, nossa equipe ainda digita o lance dele; depois que o motor responde,
anunciamos, o adversário confirma, movemos a peça e só então apertamos o
relógio. Esse tempo (``human_overhead_s``, ~10 s) sai do NOSSO relógio em todo
lance. Com 15 min + 10 s, o incremento é praticamente consumido pelo
protocolo: o "incremento líquido" (``increment - overhead``) é ~0.

Fórmula do orçamento (modo normal)
----------------------------------
::

    alvo   = peso_fase * (restante - reserva) / lances_restantes_fase
             + (incremento - overhead)
    máximo = min(alvo * max_ratio, utilizável * max_fraction)
    teto   = restante - overhead - hard_safety      (nunca ultrapassado)

Se o incremento líquido for negativo, cada lance futuro custa tempo extra e o
termo ``(incremento - overhead)`` desconta isso do alvo atual.

Abaixo de ``emergency_s`` o orçamento normal é RESTRINGIDO (nunca ampliado):
alvo <= (restante - overhead) / emergency_moves, máximo <= 1,5 * alvo e sem o
mínimo de 1 s, para garantir lances válidos rápidos.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

import chess

# Avaliações de mate são convertidas para centipeões grandes; acima disto é mate.
MATE_SCORE = 100_000
MATE_THRESHOLD = MATE_SCORE - 1_000

# Valores (em peões) usados para medir material sem peões.
_PIECE_VALUES = {chess.KNIGHT: 3, chess.BISHOP: 3, chess.ROOK: 5, chess.QUEEN: 9}


@dataclass(frozen=True)
class TimeConfig:
    """Parâmetros da gestão de tempo (espelham a seção ``[time]`` do config.toml)."""

    initial_s: float = 900.0
    increment_s: float = 10.0
    human_overhead_s: float = 10.0
    reserve_s: float = 30.0
    min_move_s: float = 1.0
    max_ratio: float = 3.0
    max_fraction: float = 0.20
    hard_safety_s: float = 5.0
    emergency_s: float = 60.0
    emergency_moves: int = 15
    absolute_min_s: float = 0.1
    tablebase_move_s: float = 0.5
    opening_until_ply: int = 24
    endgame_material: int = 24

    opening_moves_to_go: int = 40
    opening_weight: float = 0.8
    middlegame_moves_to_go: int = 32
    middlegame_weight: float = 1.15
    endgame_moves_to_go: int = 22
    endgame_weight: float = 1.0

    min_depth: int = 10
    stable_iterations: int = 5
    stable_factor: float = 0.45
    unstable_factor: float = 1.6
    eval_drop_cp: int = 25
    eval_drop_max_factor: float = 2.5


class Phase(Enum):
    OPENING = "abertura"
    MIDDLEGAME = "meio-jogo"
    ENDGAME = "final"
    TABLEBASE = "tablebase"


def non_pawn_material(board: chess.Board) -> int:
    """Soma (dos dois lados) do valor das peças que não são peões nem reis."""
    return sum(
        value * len(board.pieces(piece, color))
        for piece, value in _PIECE_VALUES.items()
        for color in chess.COLORS
    )


def classify_phase(board: chess.Board, cfg: TimeConfig, tablebase_pieces: int = 0) -> Phase:
    """
    Classifica a posição numa fase do jogo.

    ``tablebase_pieces`` é o número máximo de peças coberto pelas tablebases
    disponíveis (0 = sem tablebase). Posições com até esse número de peças
    (reis incluídos) são resolvidas pela tablebase e merecem um lance rápido.
    """
    if tablebase_pieces and chess.popcount(board.occupied) <= tablebase_pieces:
        return Phase.TABLEBASE
    if non_pawn_material(board) <= cfg.endgame_material:
        return Phase.ENDGAME
    if board.ply() < cfg.opening_until_ply:
        return Phase.OPENING
    return Phase.MIDDLEGAME


@dataclass(frozen=True)
class TimeBudget:
    """Orçamento de um lance, em segundos: ``minimum <= target <= maximum``."""

    minimum: float
    target: float
    maximum: float
    phase: Phase
    emergency: bool = False

    def __str__(self) -> str:
        tag = " EMERGÊNCIA" if self.emergency else ""
        return (f"{self.phase.value}{tag}: min {self.minimum:.1f}s "
                f"alvo {self.target:.1f}s max {self.maximum:.1f}s")


def _phase_params(phase: Phase, cfg: TimeConfig) -> tuple[int, float]:
    if phase is Phase.OPENING:
        return cfg.opening_moves_to_go, cfg.opening_weight
    if phase is Phase.ENDGAME:
        return cfg.endgame_moves_to_go, cfg.endgame_weight
    return cfg.middlegame_moves_to_go, cfg.middlegame_weight


def allocate(remaining_s: float, phase: Phase, cfg: TimeConfig,
             increment_s: Optional[float] = None) -> TimeBudget:
    """
    Calcula o orçamento de tempo para o lance atual.

    ``remaining_s`` é o tempo no nosso relógio físico no momento em que
    começamos a pensar (o overhead deste lance ainda NÃO foi descontado).
    """
    inc = cfg.increment_s if increment_s is None else increment_s
    overhead = cfg.human_overhead_s
    floor = cfg.absolute_min_s

    # Teto absoluto: o que sobra depois de pagar o overhead deste lance e uma
    # margem de segurança. Nunca pensamos além disso.
    hard_cap = max(floor, remaining_s - overhead - cfg.hard_safety_s)

    if phase is Phase.TABLEBASE:
        target = min(cfg.tablebase_move_s, hard_cap)
        return TimeBudget(min(floor, target), target, min(2 * target, hard_cap), phase)

    moves_to_go, weight = _phase_params(phase, cfg)
    usable = max(0.0, remaining_s - cfg.reserve_s)
    raw_target = weight * usable / moves_to_go + (inc - overhead)
    maximum = min(hard_cap, max(raw_target * cfg.max_ratio, floor), usable * cfg.max_fraction)
    maximum = max(maximum, floor)

    if remaining_s < cfg.emergency_s:
        # Emergência: é uma RESTRIÇÃO sobre o orçamento normal (nunca dá mais
        # tempo que ele, o que mantém o orçamento monotônico no tempo
        # restante). Sem tempo mínimo de 1 s, alvo limitado pelo que resta
        # dividido por um número fixo de lances, e quase sem extensões.
        available = max(0.0, remaining_s - overhead)
        target = min(raw_target, available / cfg.emergency_moves)
        maximum = max(floor, min(maximum, target * 1.5))
        target = _clamp(target, floor, maximum)
        return TimeBudget(floor, target, maximum, phase, emergency=True)

    minimum = min(cfg.min_move_s, maximum)
    target = _clamp(raw_target, minimum, maximum)
    return TimeBudget(minimum, target, maximum, phase)


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(value, high))


@dataclass(frozen=True)
class IterationInfo:
    """
    Resumo de uma linha ``info`` do UCI relevante para a decisão de parada.

    ``score_cp`` é do ponto de vista de quem está para jogar na raiz da busca
    (nós), com mates convertidos para ``±(MATE_SCORE - n)``.
    """

    depth: int
    best_move: str
    score_cp: int


@dataclass
class StopController:
    """
    Decide quando interromper uma busca ``go infinite``.

    Uso::

        ctl = StopController(budget, cfg, reference_cp=eval_do_lance_anterior)
        for info in iterações:
            ctl.update(info)
            if ctl.should_stop(tempo_decorrido):
                enviar stop

    Regras (aplicadas sobre o alvo do orçamento, sempre dentro de [min, max]):

    * Antes de ``min_depth`` não há confiança: limite = alvo.
    * Melhor lance estável por ``stable_iterations`` profundidades seguidas:
      limite = alvo * ``stable_factor`` (para cedo). Entre 0 e esse número,
      interpola linearmente.
    * Melhor lance mudou na última profundidade: limite = alvo * ``unstable_factor``.
    * Avaliação caiu ``eval_drop_cp`` ou mais (em relação à referência — eval
      do lance anterior ou primeira iteração confiável — ou à iteração
      anterior): estende proporcionalmente à queda, até
      ``eval_drop_max_factor``.
    * Mate a nosso favor com lance estável: para cedo.
    """

    budget: TimeBudget
    cfg: TimeConfig
    reference_cp: Optional[int] = None

    depth: int = field(default=0, init=False)
    best_move: Optional[str] = field(default=None, init=False)
    score_cp: Optional[int] = field(default=None, init=False)
    stable_count: int = field(default=0, init=False)
    _prev_score: Optional[int] = field(default=None, init=False)
    _first_trusted_score: Optional[int] = field(default=None, init=False)
    _changed_at_depth: Optional[int] = field(default=None, init=False)

    def update(self, info: IterationInfo) -> None:
        """Registra uma nova iteração (ou atualização de PV na mesma profundidade)."""
        if not info.best_move:
            return
        if self.best_move is None:
            self.stable_count = 0
        elif info.best_move != self.best_move:
            self.stable_count = 0
            self._changed_at_depth = info.depth
        elif info.depth > self.depth:
            self.stable_count += 1

        if info.depth > self.depth:
            self._prev_score = self.score_cp
        self.best_move = info.best_move
        self.depth = max(self.depth, info.depth)
        self.score_cp = info.score_cp
        if self._first_trusted_score is None and info.depth >= self.cfg.min_depth:
            self._first_trusted_score = info.score_cp

    @property
    def trusted(self) -> bool:
        return self.best_move is not None and self.depth >= self.cfg.min_depth

    def eval_drop(self) -> int:
        """Maior queda de avaliação observada (cp, >= 0)."""
        if self.score_cp is None:
            return 0
        drops = [0]
        ref = self.reference_cp if self.reference_cp is not None else self._first_trusted_score
        if ref is not None:
            drops.append(ref - self.score_cp)
        if self._prev_score is not None:
            drops.append(self._prev_score - self.score_cp)
        # Comparar com avaliações de mate não faz sentido em cp: limita a queda.
        return min(max(drops), 10 * self.cfg.eval_drop_cp)

    def time_factor(self) -> float:
        """Multiplicador aplicado ao alvo do orçamento."""
        cfg = self.cfg
        if not self.trusted:
            return 1.0

        recently_changed = (self._changed_at_depth is not None
                            and self.depth - self._changed_at_depth <= 1)
        if recently_changed:
            factor = cfg.unstable_factor
        else:
            progress = min(self.stable_count, cfg.stable_iterations) / cfg.stable_iterations
            factor = 1.0 - (1.0 - cfg.stable_factor) * progress

        drop = self.eval_drop()
        if drop >= cfg.eval_drop_cp:
            extension = min(cfg.eval_drop_max_factor, 1.0 + 0.5 * drop / cfg.eval_drop_cp)
            factor = max(factor, 1.0) * extension

        if self.score_cp is not None and self.score_cp >= MATE_THRESHOLD and self.stable_count >= 2:
            factor = min(factor, cfg.stable_factor)
        return factor

    def time_limit(self) -> float:
        """Tempo (s) a partir do qual a busca deve ser interrompida, no estado atual."""
        b = self.budget
        return _clamp(b.target * self.time_factor(), b.minimum, b.maximum)

    def should_stop(self, elapsed_s: float) -> bool:
        b = self.budget
        if elapsed_s >= b.maximum:
            return True
        if elapsed_s < b.minimum:
            return False
        return elapsed_s >= self.time_limit()


@dataclass
class ClockTracker:
    """
    Estimativa dos dois relógios físicos (segundos).

    É atualizada a cada lance e corrigida manualmente pelo comando ``clock``.
    No nosso lance desconta o tempo de pensamento mais o overhead humano e
    soma o incremento; no do adversário desconta o tempo de parede observado.
    """

    mine: float
    opponent: float
    increment_s: float
    overhead_s: float

    def my_move_done(self, think_s: float) -> None:
        self.mine = max(0.0, self.mine - think_s - self.overhead_s) + self.increment_s

    def opponent_move_done(self, elapsed_s: float) -> None:
        self.opponent = max(0.0, self.opponent - elapsed_s) + self.increment_s

    def sync(self, mine: float, opponent: float) -> None:
        self.mine = mine
        self.opponent = opponent


def parse_clock(text: str) -> float:
    """Converte ``"754"``, ``"12:34"`` ou ``"1:02:03"`` para segundos."""
    parts = text.strip().split(":")
    if not 1 <= len(parts) <= 3 or any(p == "" for p in parts):
        raise ValueError(f"tempo inválido: {text!r}")
    seconds = 0.0
    for part in parts:
        value = float(part)
        if value < 0:
            raise ValueError(f"tempo negativo: {text!r}")
        seconds = seconds * 60 + value
    return seconds


def format_clock(seconds: float) -> str:
    seconds = max(0, int(round(seconds)))
    return f"{seconds // 60}:{seconds % 60:02d}"
