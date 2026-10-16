"""
Autor: Pedro Danilo, Yan
Copyrigth: 2023

Descrição: Motor de xadrez para o III Chess Challenge. Interface gráfica em
PyQt5 controlando o Stockfish (UCI) com gestão de tempo própria
(chessbot/time_manager.py).

Ambiente virtual (opcional): python -m venv .venv
Como instalar: pip install -r requirements.txt
Como executar: python main.py [--config config.toml]
Testes: python -m pytest
"""

# Importações padrão do Python
import argparse
import sys
import threading
from pathlib import Path

import chess
import chess.svg

# Importações PyQt5 (bliblioteca de interface gráfica)
from PyQt5.QtCore import QObject, QTimer, pyqtSignal
from PyQt5.QtGui import QFont
from PyQt5.QtSvg import QSvgWidget
from PyQt5.QtWidgets import (QApplication, QHBoxLayout, QLabel, QLineEdit, QMainWindow,
                             QMessageBox, QPushButton, QVBoxLayout, QWidget)

from chessbot.book import OpeningBook
from chessbot.config import load_config
from chessbot.engine import Engine
from chessbot.game import GameController, color_name
from chessbot.game_logger import format_score


class EngineSignals(QObject):
    """Ponte thread do motor -> thread da interface."""
    info = pyqtSignal(str)
    done = pyqtSignal(object)
    failed = pyqtSignal(object)


class ChessGUI(QMainWindow):
    """
    Classe que representa a interface gráfica do jogo de xadrez.
    """

    def __init__(self, controller: GameController):
        super(ChessGUI, self).__init__()
        self.game = controller
        self.worker = None
        self.signals = EngineSignals()
        self.signals.info.connect(self.on_engine_info)
        self.signals.done.connect(self.on_engine_done)
        self.signals.failed.connect(self.on_engine_failed)

        # Inicializa o widget central
        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)

        # Inicializa o layout principal
        self.layout = QVBoxLayout(self.central_widget)
        self.layout.setSpacing(5)

        # Layout para escolher a cor das peças (cor do NOSSO motor)
        self.color_layout = QHBoxLayout()
        self.white_button = QPushButton("Motor de Brancas", self)
        self.white_button.clicked.connect(lambda: self.submit("new white"))
        self.black_button = QPushButton("Motor de Pretas", self)
        self.black_button.clicked.connect(lambda: self.submit("new black"))
        self.color_layout.addWidget(self.white_button)
        self.color_layout.addWidget(self.black_button)
        self.layout.addLayout(self.color_layout)

        # Relógios estimados
        self.clock_label = QLabel(self)
        self.clock_label.setFont(QFont("Consolas", 14, QFont.Bold))
        self.layout.addWidget(self.clock_label)

        # Inicializa o widget que mostra o tabuleiro
        self.svg_widget = QSvgWidget(self)
        self.svg_widget.setMinimumSize(480, 480)
        self.layout.addWidget(self.svg_widget)

        # Lance do motor em destaque, para o anúncio verbal
        self.movimento_label = QLabel("Último lance do motor: n/a", self)
        self.movimento_label.setFont(QFont("Consolas", 22, QFont.Bold))
        self.layout.addWidget(self.movimento_label)

        # Informações da busca (profundidade, avaliação, PV)
        self.info_label = QLabel("", self)
        self.info_label.setWordWrap(True)
        self.info_label.setFont(QFont("Consolas", 9))
        self.layout.addWidget(self.info_label)

        # Inicializa o input para o movimento / comandos
        self.move_input = QLineEdit(self)
        self.move_input.setFont(QFont("Consolas", 14))
        self.move_input.setPlaceholderText("lance UCI (e2e4) ou comando: undo | fen ... | clock 12:34 11:02 | go | now | help")
        self.move_input.returnPressed.connect(self.make_next_move)
        self.layout.addWidget(self.move_input)

        # Inicializa o botão para enviar o movimento
        self.move_button = QPushButton("Enviar (Enter)", self)
        self.move_button.clicked.connect(self.make_next_move)
        self.layout.addWidget(self.move_button)

        # Inicializa o label para mostrar o status do jogo
        self.status_label = QLabel("Status: escolha a cor do motor (ou 'new white' / 'new black')", self)
        self.status_label.setWordWrap(True)
        self.layout.addWidget(self.status_label)

        # Configurações da janela
        self.setWindowTitle(f"Chess Challenge — {controller.engine.name}")
        self.setGeometry(100, 50, 560, 860)

        self.clock_timer = QTimer(self)
        self.clock_timer.timeout.connect(self.update_clock_display)
        self.clock_timer.start(250)

        self.update_board_display()
        self.update_clock_display()

    def update_board_display(self):
        """
        Atualiza o widget que mostra o tabuleiro.
        """
        board = self.game.board
        orientation = self.game.my_color if self.game.my_color is not None else chess.WHITE
        lastmove = board.peek() if board.move_stack else None
        check = board.king(board.turn) if board.is_check() else None
        svg = chess.svg.board(board=board, orientation=orientation, lastmove=lastmove, check=check)
        self.svg_widget.load(svg.encode("utf-8"))

    def update_clock_display(self):
        self.clock_label.setText(self.game.clock_text())

    def set_status(self, text, ok=True):
        self.status_label.setText(f"Status: {text}")
        self.status_label.setStyleSheet("" if ok else "color: #c62828; font-weight: bold;")

    def make_next_move(self):
        """
        Envia o texto digitado (lance ou comando).
        """
        text = self.move_input.text()
        if self.submit(text):
            self.move_input.clear()

    def submit(self, text):
        response = self.game.handle(text)
        self.set_status(response.message, response.ok)
        self.update_board_display()
        if response.ok and self.game.my_color is not None and text.strip().startswith("new"):
            self.movimento_label.setText("Último lance do motor: n/a")
            self.info_label.setText(f"log: {self.game.logger.path}")
        if response.think:
            self.make_ai_move()
        return response.ok

    def make_ai_move(self):
        """
        Inicia a busca do motor numa thread separada.
        """
        session = self.game.prepare_think()
        hit = " (ponder acertou)" if session is not None else ""
        self.set_status(f"motor pensando{hit}... ('now' força o lance)")

        def on_info(info, ctl, elapsed):
            pv = " ".join(m.uci() for m in info["pv"][:8])
            self.signals.info.emit(
                f"prof {info.get('depth')}/{info.get('seldepth', '-')} | aval {format_score(info.get('score'))} "
                f"| nós {info.get('nodes', '-')} | {elapsed:.1f}s de {ctl.time_limit():.1f}s "
                f"(máx {ctl.budget.maximum:.1f}s) | estável {ctl.stable_count}\nPV: {pv}")

        def run():
            try:
                self.signals.done.emit(self.game.think(session, on_info))
            except Exception as exc:  # noqa: BLE001 - mostrado na interface e no log
                self.signals.failed.emit(exc)

        self.worker = threading.Thread(target=run, daemon=True)
        self.worker.start()

    def on_engine_info(self, text):
        self.info_label.setText(text)

    def on_engine_done(self, result):
        response = self.game.finish_think(result)
        self.movimento_label.setText(f"MOTOR JOGA: {result.move.uci()}")
        ponder = self.game.ponder_move
        details = f"{result.source} | {result.elapsed:.1f}s | prof {result.depth or '-'} | aval {format_score(result.score)}"
        if result.budget is not None:
            details += f"\norçamento: {result.budget}"
        if ponder is not None:
            details += f"\nponder: esperando {ponder.uci()}"
        self.info_label.setText(details)
        self.set_status(f"{response.message} — anuncie e depois digite o lance das "
                        f"{color_name(not self.game.my_color)}")
        self.update_board_display()

    def on_engine_failed(self, error):
        response = self.game.abort_think(error)
        self.set_status(response.message, ok=False)

    def closeEvent(self, event):
        self.game.force.set()
        if self.worker is not None:
            self.worker.join(timeout=3)
        self.game.close()
        self.game.engine.quit()
        super().closeEvent(event)


if __name__ == "__main__":
    """
    Função principal.
    """
    parser = argparse.ArgumentParser(description="Motor do III Chess Challenge")
    parser.add_argument("--config", default=str(Path(__file__).with_name("config.toml")))
    args = parser.parse_args()

    app = QApplication(sys.argv)
    try:
        config = load_config(args.config)
        engine = Engine(config.engine)
    except Exception as exc:  # noqa: BLE001
        QMessageBox.critical(None, "Erro ao iniciar", str(exc))
        sys.exit(1)
    book = OpeningBook(config.book_path, config.book_max_plies)

    gui = ChessGUI(GameController(config, engine, book))
    gui.set_status(f"{book.status} | tablebase até {engine.tablebase_pieces} peças — escolha a cor do motor")
    gui.show()

    sys.exit(app.exec_())
