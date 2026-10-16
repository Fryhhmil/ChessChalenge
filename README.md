# ChessChalenge — motor para o III Chess Challenge

Motor de xadrez para partidas em tabuleiro físico. Um wrapper em Python
(`python-chess` + PyQt5) controla o **Stockfish** como processo externo via UCI.
A decisão de **quanto tempo pensar e quando parar** é feita por um componente
próprio, a **gestão de tempo** (`chessbot/time_manager.py`).

Autores: Pedro Danilo, Yan Sá

---

## Sumário

1. [Requisitos](#requisitos)
2. [Instalação](#instalação)
3. [Configuração](#configuração)
4. [Como jogar uma partida](#como-jogar-uma-partida)
5. [Log da partida](#log-da-partida)
6. [Atendimento às regras da competição](#atendimento-às-regras-da-competição)
7. [Modificação significativa: gestão de tempo](#modificação-significativa-gestão-de-tempo)
8. [Estrutura do projeto](#estrutura-do-projeto)
9. [Testes](#testes)

---

## Requisitos

| Item | Versão / observação |
|---|---|
| Sistema operacional | Windows 10/11 x64 (testado no Windows 11) |
| Python | 3.11 ou superior (testado no 3.14). No 3.10 funciona com `tomli`, já declarado no `requirements.txt` |
| Stockfish | Binário UCI local. Testado com **Stockfish 19** (`stockfish-windows-x86-64-universal.exe`) |
| Tablebases Syzygy | Arquivos `.rtbw`/`.rtbz` de **3, 4 e 5 peças** (~940 MB) |
| Opening book | Arquivo Polyglot `.bin` (opcional; sem ele o motor joga sem book) |

Dependências Python (em `requirements.txt`):

```
chess>=1.11      # estado do jogo, UCI, Polyglot
PyQt5>=5.15      # interface gráfica
tomli>=2.0       # só para Python < 3.11 (leitura do config.toml)
pytest>=8.0      # testes
```

> O projeto **não faz nenhuma requisição de rede**. Tudo (motor, book,
> tablebases) é lido do disco local, então pode rodar com o Wi-Fi desligado.

---

## Instalação

Faça a instalação **antes** do evento, com internet. Durante a partida nada é baixado.

```powershell
# 1. Clonar o repositório
git clone https://github.com/Fryhhmil/ChessChalenge.git
cd ChessChalenge

# 2. Criar e ativar o ambiente virtual
python -m venv .venv
.venv\Scripts\activate

# 3. Instalar as dependências
pip install -r requirements.txt
```

### Arquivos que não estão no git

Por serem grandes, o binário do Stockfish e as tablebases ficam fora do
repositório (veja o `.gitignore`). Coloque-os nestes caminhos (ou ajuste o
`config.toml`):

```
ChessChalenge/
├── engines/
│   └── stockfish-windows-x86-64-universal.exe   # extraído do zip oficial do Stockfish
└── assets/
    ├── Titans.bin                                # opening book Polyglot (opcional)
    └── syzygy/                                   # *.rtbw e *.rtbz de 3, 4 e 5 peças
```

- **Stockfish:** baixe em <https://stockfishchess.org/download/> e extraia o
  `.exe` para `engines/`.
- **Syzygy 3–5 peças:** por exemplo em <https://tablebase.lichess.ovh/tables/standard/3-4-5/>.
  **Não** coloque tabelas de 6 ou 7 peças. Mesmo que estejam na pasta, o motor
  é configurado com `SyzygyProbeLimit=5`.
- **Book:** qualquer `.bin` Polyglot. Se o arquivo não existir ou estiver
  vazio, o programa avisa e joga sem book.

### Verificar a instalação

```powershell
python -m pytest
```

Todos os testes devem passar. Os testes de integração usam o Stockfish real e
são pulados automaticamente se o binário não estiver em `engines/`.

---

## Configuração

Tudo fica em `config.toml`. Os caminhos relativos são resolvidos a partir da pasta do arquivo.

```toml
[engine]
path = "engines/stockfish-windows-x86-64-universal.exe"
threads = 12
hash_mb = 1024
syzygy_path = "assets/syzygy"
syzygy_probe_limit = 5      # validado: o programa recusa valores > 5

[book]
path = "assets/Titans.bin"
max_plies = 10              # validado: o programa recusa valores > 10

[time]
initial_s = 900             # 15 min
increment_s = 10
human_overhead_s = 10       # tempo gasto pelo protocolo físico a cada lance
# ... demais parâmetros da gestão de tempo (comentados no arquivo)
```

Ajuste `threads` e `hash_mb` para a máquina do evento. O parâmetro mais
importante a calibrar é `human_overhead_s`: cronometre, em partidas de treino,
quanto tempo a equipe gasta de fato para anunciar, confirmar, mover, apertar o
relógio e digitar o lance do adversário.

---

## Como jogar uma partida

```powershell
.venv\Scripts\activate
python main.py                       # usa config.toml
python main.py --config outro.toml   # outra configuração
```

1. Clique em **Motor de Brancas** ou **Motor de Pretas** (ou digite `new white` / `new black`).
2. Quando o motor joga, o lance aparece em destaque (**MOTOR JOGA: e2e4**).
   Anuncie em voz alta, espere a confirmação, mova a peça e aperte o relógio.
3. Quando o adversário jogar, digite o lance dele em UCI e tecle **Enter**.
   O motor começa a pensar sozinho.
4. De tempos em tempos, sincronize com o relógio físico: `clock 12:34 11:02`.

### Comandos

| Comando | Efeito |
|---|---|
| `e2e4`, `e7e8q` | Lance do adversário em UCI (a legalidade é validada; promoção sem a peça gera uma dica) |
| `undo` | Desfaz o último meio-lance |
| `fen <FEN>` | Ressincroniza com o tabuleiro físico (a fonte da verdade) |
| `clock <meu> <adv>` | Sincroniza os relógios (`754`, `12:34` ou `1:02:03`) |
| `new white` / `new black` | Nova partida; a cor é a do **nosso** motor |
| `go` | Manda o motor pensar (usado depois de `undo`/`fen` quando é a vez dele) |
| `now` | Força o motor a jogar imediatamente |
| `help` | Lista os comandos |

Enquanto o motor pensa, só `now`, `clock` e `help` são aceitos.

---

## Log da partida

Cada partida gera um arquivo próprio em `logs/`, por exemplo
`logs/partida_20261016-170508_pretas.log`. O arquivo é gravado e descarregado a
cada linha, então sobrevive a um travamento.

```
# [17:05:08] motor: Stockfish 19
# [17:05:08] opções UCI: Threads=12, Hash=1024, SyzygyPath=...\assets\syzygy, SyzygyProbeLimit=5
# [17:05:08] book: limite de 10 meios-lances
# [17:05:08] aval = ponto de vista das brancas (peões; #n = mate); prof = profundidade/seldepth
lance | cor | uci | prof | nos | aval | tempo_s | origem | pv
1 | brancas | h2h3 | - | - | - | 4.20 | adversario | -
# [17:05:09] orçamento abertura: min 1.0s alvo 17.4s max 52.2s; relógio no início do lance 15:00; parou em 9.31s
1 | pretas | e7e5 | 28/41 | 98765432 | -0.04 | 9.31 | motor | e7e5 e2e4 g8f6 b1c3 ...
```

| Campo exigido | Coluna |
|---|---|
| Número do lance | `lance` |
| Cor | `cor` |
| Lance em UCI | `uci` |
| Profundidade | `prof` (profundidade/seldepth) |
| Nós avaliados | `nos` |
| Avaliação | `aval` (ponto de vista das brancas, em peões; `#n` = mate) |
| PV | `pv` |
| Tempo gasto | `tempo_s` |

A coluna `origem` indica de onde veio o lance: `motor`, `ponder-hit`, `book`,
`forcado` (lance único) ou `adversario`. As linhas `#` registram o orçamento de
tempo de cada lance e todos os comandos de correção (`undo`, `fen`, `clock`).

---

## Atendimento às regras da competição

| Regra | Como é atendida |
|---|---|
| Tudo local, sem rede | Stockfish, book e tablebases vêm do disco; não há código de rede no projeto |
| Relógio 15 min + 10 s; vale o físico | Tempo e incremento estão no `config.toml`. O comando `clock` sincroniza com o relógio físico, e a gestão de tempo desconta o overhead humano de cada lance |
| Protocolo de lance (anúncio, confirmação, digitação) | O lance do motor aparece em destaque para o anúncio. Os lances do adversário são digitados e validados. `undo` e `fen` corrigem divergências com o tabuleiro físico |
| Book Polyglot com limite rígido de 10 meios-lances | `chessbot/book.py` só consulta o book enquanto `board.ply() < 10`. O limite vem do número do lance da posição, então também vale depois de um `fen`. O config recusa `max_plies > 10`. Coberto por testes (`tests/test_book.py` e o teste de partida completa) |
| Syzygy só até 5 peças | O motor é iniciado com `SyzygyProbeLimit=5`, o config recusa valores maiores e só há tabelas de 3 a 5 peças em `assets/syzygy` |
| Ponder permitido | Durante o turno do adversário o motor analisa a posição esperada. Se ele jogar o lance previsto, a análise é reaproveitada |
| Log obrigatório (.log) | `chessbot/game_logger.py`: um arquivo por partida com todos os campos exigidos |
| Dependências em `requirements.txt` | Arquivo renomeado (antes estava `requeriments.txt`) e completado |
| Modificação significativa de autoria própria | Gestão de tempo própria, detalhada na próxima seção. O Stockfish não recebe nenhum parâmetro de tempo |

---

## Modificação significativa: gestão de tempo

O Stockfish é usado apenas como **calculadora**. Toda busca é iniciada com
`go infinite`, e o próprio programa decide quando enviar `stop`. O
gerenciamento de tempo interno do Stockfish (`go wtime/btime/winc/movetime`)
**nunca é usado**, e há um teste de integração que captura o tráfego UCI e
falha se algum desses comandos aparecer.

O módulo `chessbot/time_manager.py` é de autoria própria, puro (sem I/O, sem
relógio do sistema, sem processo UCI) e coberto por testes unitários. Ele tem
quatro partes.

### 1. Classificação da fase do jogo

`classify_phase()` olha a posição atual:

- **tablebase**: até 5 peças no tabuleiro (reis incluídos) e Syzygy disponível;
- **final**: material sem peões (soma dos dois lados) ≤ 24;
- **abertura**: primeiros 24 meios-lances (já fora do book);
- **meio-jogo**: o resto.

### 2. Orçamento por lance

`allocate()` devolve um orçamento `mínimo ≤ alvo ≤ máximo` a partir do tempo
restante, do incremento e do **overhead humano**:

```
alvo   = peso_fase × (restante − reserva) / lances_restantes_fase + (incremento − overhead)
máximo = min(alvo × 3, (restante − reserva) × 20%)
teto   = restante − overhead − margem_segurança        (nunca ultrapassado)
```

| Fase | Lances restantes estimados | Peso |
|---|---|---|
| Abertura (pós-book) | 40 | 0,8 |
| Meio-jogo | 32 | 1,15 |
| Final | 22 | 1,0 |

- **Overhead humano.** No tabuleiro físico, anunciar, confirmar, mover, apertar o
  relógio e digitar o lance do adversário consome ~10 s do **nosso** relógio a
  cada lance. Com 10 s de incremento, o ganho líquido é praticamente zero, e o
  orçamento leva isso em conta. Se o overhead for maior que o incremento, cada
  lance futuro fica mais caro e o alvo atual é reduzido.
- **Tablebase.** Com até 5 peças, o lance sai em ~0,5 s.
- **Modo de emergência.** Abaixo de 60 s no relógio, o orçamento normal é
  **restringido**: o alvo fica limitado a `(restante − overhead) / 15`, o máximo
  a 1,5 × o alvo, e cai o mínimo de 1 s. Como só restringe, o orçamento nunca
  aumenta quando o relógio diminui (propriedade verificada nos testes).

### 3. Critério de parada dinâmico

O `StopController` recebe cada iteração da busca (profundidade, melhor lance,
avaliação) e decide a todo instante se já é hora de mandar `stop`:

| Situação | Tempo usado |
|---|---|
| Profundidade < 10 (ainda sem confiança) | alvo |
| Melhor lance estável por 5 profundidades seguidas | 45% do alvo (para cedo) |
| Melhor lance acabou de mudar | 160% do alvo (estende) |
| Avaliação caiu ≥ 25 cp (em relação ao lance anterior ou à iteração anterior) | estende proporcionalmente à queda, até 2,5× |
| Mate encontrado a nosso favor com lance estável | para cedo |
| Em qualquer caso | nunca antes do mínimo, nunca depois do máximo |

### 4. Estimativa do relógio físico

O `ClockTracker` acompanha os dois relógios. Em cada lance nosso desconta o
tempo pensado mais o overhead e soma o incremento. A estimativa é corrigida
manualmente com o comando `clock`.

### Integração com o ponder

Depois do nosso lance, o motor analisa (`go infinite`) a posição resultante do
lance que espera do adversário (o 2º lance da PV). Se o adversário jogar esse
lance, a busca **continua** e o `StopController` recebe todo o histórico de
iterações. Com isso o lance costuma ser decidido logo, por estabilidade,
economizando relógio. Se o adversário jogar outro lance, a análise é descartada
e uma nova busca começa.

---

## Estrutura do projeto

```
main.py                    # interface gráfica PyQt5 (ponto de entrada)
config.toml                # caminhos, opções UCI e parâmetros de tempo
requirements.txt
chessbot/
  time_manager.py          # ★ gestão de tempo (componente autoral)
  search.py                # book → lance único → busca com parada pela gestão de tempo
  engine.py                # wrapper UCI do Stockfish (go infinite / stop)
  book.py                  # opening book Polyglot com limite de 10 meios-lances
  game.py                  # estado oficial da partida, comandos, ponder, relógio
  commands.py              # parser dos comandos digitados
  game_logger.py           # log obrigatório da partida
  config.py                # leitura e validação do config.toml
tests/
  test_time_manager.py     # orçamento, fases, emergência, parada dinâmica, relógio
  test_book.py             # limite rígido do book (incl. fen e undo)
  test_commands.py
  test_logger.py
  test_integration.py      # partidas reais contra o Stockfish
```

### O que mudou em relação à versão original

A versão original era uma interface PyQt5 que jogava **lances aleatórios**
(`random.choice`). Mudanças:

- a "IA" aleatória foi substituída pelo Stockfish via UCI, com a gestão de tempo própria;
- regras, estado e motor saíram da classe da interface para o pacote `chessbot/`, que é testável;
- a validação de lances ficou robusta: entrada malformada não derruba mais o programa;
- foram adicionados os comandos `undo`, `fen`, `clock`, `new`, `go` e `now`;
- foram adicionados o book com limite, as tablebases até 5 peças, o ponder e o log obrigatório;
- a interface ganhou relógios, o lance do motor em destaque, as informações da busca e o tabuleiro orientado pela nossa cor;
- `requeriments.txt` virou `requirements.txt` e o `docker-compose.yml` vazio foi removido.

---

## Testes

```powershell
python -m pytest        # suíte completa (~5 s)
python -m pytest -v tests/test_time_manager.py tests/test_book.py
```

O que os testes cobrem:

- **gestão de tempo:** ordem `mínimo ≤ alvo ≤ máximo`, o teto nunca é
  ultrapassado, o orçamento é monotônico no tempo restante, efeito do overhead e
  do incremento, emergência, tablebase, parada por estabilidade, extensão por
  queda de avaliação e por troca do melhor lance, limite máximo, mate;
- **book:** usado até o 10º meio-lance e cortado a partir dele, inclusive depois de `fen` e `undo`;
- **integração:** partida completa com o Stockfish real (sem `wtime/btime`, log
  completo), acerto e erro do ponder, final de tablebase rápido e comandos.
