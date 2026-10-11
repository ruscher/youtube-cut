# 05 — Instalação, execução e testes

## Dependências

| Pacote (Arch) | Para quê |
|---|---|
| `python` ≥ 3.11 | linguagem |
| `pyside6` | interface Qt Quick (usa o Qt do sistema) |
| `yt-dlp` | listagem, legendas e download de trechos |
| `ffmpeg` | corte e reencode (VA-API opcional: `libva-mesa-driver` ou `intel-media-driver`) |
| `nodejs` ou `deno` | runtime JS exigido pelo YouTube para resolver desafios |
| `yt-dlp-ejs` (opcional) | scripts do solucionador, sem baixar do GitHub |

### Como pacote (recomendado)

```bash
cd packaging/arch
makepkg -si                 # instala makedepends (python-build, python-installer…), gera e instala
youtube-cut                 # interface
youtube-cut scan --help
sudo pacman -R youtube-cut  # remover
```

O `PKGBUILD` usa o próprio repositório como fonte (`$startdir/../..`), gera o wheel com
`python -m build --no-isolation` e instala com `python -m installer`, mais o `.desktop`, o
ícone em `hicolor/scalable` e o README.

### Sem instalar

```bash
sudo pacman -S --needed python pyside6 yt-dlp ffmpeg nodejs
PYTHONPATH=src python -m youtube_cut
```

`pip install --user` é bloqueado no Arch (PEP 668, `externally-managed-environment`). Para
desenvolver, use um venv com `--system-site-packages` (ele reaproveita o PySide6 do sistema):

```bash
python -m venv --system-site-packages .venv
.venv/bin/pip install -e . pytest
.venv/bin/youtube-cut
```

## Onde ficam os dados

| Caminho | Conteúdo |
|---|---|
| `~/.config/youtube-cut/settings.json` | preferências da interface |
| `~/.cache/youtube-cut/subtitles/` | legendas baixadas (pode apagar à vontade) |
| `~/Vídeos/YouTube Cut/<termos>/` | cortes (configurável) |

## Testes

```bash
python -m venv --system-site-packages .venv
.venv/bin/pip install yt-dlp pytest
.venv/bin/python -m pytest                 # ~100 testes, offline, ~6 s
.venv/bin/python -m pytest --run-network   # + smoke test no YouTube real
```

| Arquivo | Cobre |
|---|---|
| `test_core.py` | timestamps, VTT rolante do YouTube, SRT, busca, trechos, links aceitos, escolha de faixa |
| `test_search_perf.py` | limite de tempo da busca fuzzy e equivalência com a força bruta |
| `test_local.py` | vídeo sintético gerado pelo FFmpeg: descoberta, legenda embutida, corte preciso/rápido/VA-API, cancelamento, relatório |
| `test_youtube.py` | cliente com yt-dlp substituído por um dublê: cache, marcador sem-legenda, 429, retry de trecho, cancelamento |
| `test_cli.py` | `youtube-cut scan` ponta a ponta em pasta local, códigos de saída, restauração do SIGINT |
| `test_gui.py` | modelos Qt, backend (busca, corte, filtro, cancelamento), ícones, `Main.qml` carregando sem avisos |
| `test_packaging.py` | ícone, `.desktop` validado, `package-data` cobrindo todo o QML, documentação |
| `test_theme.py` | contraste WCAG AA de todas as cores de texto, nos dois temas |

Os testes isolam `~/.config` e `~/.cache` em diretórios temporários (`conftest.py`) e rodam a
interface com `QT_QPA_PLATFORM=offscreen` e `QT_QUICK_BACKEND=software`.

## Solução de problemas

| Sintoma | Causa provável → solução |
|---|---|
| "O YouTube pediu confirmação de login" | Configurações → Usar login do navegador |
| "HTTP 429" na barra de status | limite de requisições; o app espera e tenta de novo. Reduza "Vídeos por busca" |
| "O YouTube interrompeu o download do trecho" | conexão recusada pelo googlevideo; clique em Cortar de novo (os já salvos são pulados) |
| Vídeo "Sem legenda" | transcrição ainda não gerada (lives longas/recentes) ou desativada pelo canal |
| Nome não encontrado | ative a tolerância a erros ou adicione grafias alternativas |
| Corte local lento | ative VA-API (Configurações → Aceleração) ou desligue o corte preciso |
