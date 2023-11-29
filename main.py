"""
Autor: Pedro Danilo, Yan
Copyrigth: 2023

Descrição: Este é um jogo de xadrez feito em Python com interface gráfica.

Ambiente virtual (opcional): python -m venv venv
Como instalar: pip install -r requirements.txt
Como executar: python main.py
"""

# Importações padrão do Python
import sys
import chess
import chess.svg
import random

# Importações PyQt5 (bliblioteca de interface gráfica)
from PyQt5.QtCore import Qt
from PyQt5.QtSvg import QSvgWidget
from PyQt5.QtWidgets import QApplication, QMainWindow, QVBoxLayout, QPushButton, QWidget, QLineEdit, QLabel, QHBoxLayout


class ChessGUI(QMainWindow):
    """
    Classe que representa a interface gráfica do jogo de xadrez.
    """
    def __init__(self):
        super(ChessGUI, self).__init__()

        # Inicializa o tabuleiro
        self.board = chess.Board()

        # Inicializa o widget central
        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)

        # Inicializa o layout principal
        self.layout = QVBoxLayout(self.central_widget)
        self.layout.setSpacing(5)

        # Layout para escolher a cor das peças
        self.color_layout = QHBoxLayout()
        self.white_button = QPushButton("Brancas", self)
        self.white_button.clicked.connect(lambda: self.start_game(chess.WHITE))
        self.black_button = QPushButton("Pretas", self)
        self.black_button.clicked.connect(lambda: self.start_game(chess.BLACK))
        self.color_layout.addWidget(self.white_button)
        self.color_layout.addWidget(self.black_button)
        self.layout.addLayout(self.color_layout)

        # Inicializa o widget que mostra o tabuleiro
        self.svg_widget = QSvgWidget(self)
        self.update_board_display()
        self.layout.addWidget(self.svg_widget)

        # Inicializa o input para o movimento
        self.move_input = QLineEdit(self)
        self.layout.addWidget(self.move_input)

        # Inicializa o botão para enviar o movimento
        self.move_button = QPushButton("Enviar movimento (exemplo: e2e4)", self)
        self.move_button.clicked.connect(self.make_next_move)
        self.layout.addWidget(self.move_button)

        # Inicializa o label para mostrar o status do jogo
        self.status_label = QLabel("Status: esperando a entrada", self)
        self.status_label.setMinimumHeight(20)
        self.status_label.setMaximumHeight(20)
        self.layout.addWidget(self.status_label)

        # Configurações da janela
        self.setWindowTitle("Chess GUI")
        self.setGeometry(100, 100, 450, 500)

        # Inicializa o jogador atual
        self.current_player = None

    def update_board_display(self):
        """
        Atualiza o widget que mostra o tabuleiro.
        """
        svg = chess.svg.board(board=self.board)
        self.svg_widget.load(svg.encode("utf-8"))

    def make_next_move(self):
        """
        Faz o próximo movimento.
        """
        # Verifica se o jogo não acabou e se é a vez do jogador
        if self.current_player is not None and not self.board.is_game_over():
            move_uci = self.move_input.text()
            
            # Verifica se o movimento é válido
            if chess.Move.from_uci(move_uci) in self.board.legal_moves:
                self.board.push_uci(move_uci)
                self.update_board_display()

                # Verifica se o jogo acabou
                if self.board.is_game_over():
                    self.status_label.setText("Game Over!")
                else:
                    self.toggle_current_player()
                    self.status_label.setText(f"Status: esperando o movimento das {'Brancas' if self.current_player == chess.WHITE else 'Pretas'}")
                    
                    # Se as Pretas começarem, a IA faz o primeiro movimento
                    if self.current_player == chess.BLACK:
                        self.make_ai_move()
            else:
                self.status_label.setText("Movimento inválido!")

    def make_ai_move(self):
        """
        Faz o próximo movimento da IA.
        """
        legal_moves = list(self.board.legal_moves)
        
        # Verifica se o jogo não acabou e se é a vez da IA
        if legal_moves:
            move = random.choice(legal_moves)
            self.board.push(move)
            self.update_board_display()
            self.toggle_current_player()

    def toggle_current_player(self):
        """
        Alterna o jogador atual.
        """
        self.current_player = chess.BLACK if self.current_player == chess.WHITE else chess.WHITE

    def start_game(self, chosen_color):
        """
        Inicia o jogo.
        """
        self.current_player = chosen_color
        self.status_label.setText(f"Status: esperando o movimento das {'Brancas' if self.current_player == chess.WHITE else 'Pretas'}")
        self.color_layout.setEnabled(False)

        # Se as Pretas começarem, a IA faz o primeiro movimento
        if self.current_player == chess.BLACK:
            self.make_ai_move()

if __name__ == "__main__":
    """
    Função principal.
    """
    app = QApplication(sys.argv)

    gui = ChessGUI()
    gui.show()

    sys.exit(app.exec_())

