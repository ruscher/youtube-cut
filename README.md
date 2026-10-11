# YouTube Cut

Encontre o momento exato em que um nome (ou qualquer palavra) é dito nos vídeos de um canal
do YouTube e recorte só aqueles trechos, sem baixar as lives inteiras.

![Ícone](data/youtube-cut.svg)

- **Cole qualquer link**: canal, `@handle`, link do **YouTube Studio**
  (`studio.youtube.com/channel/…/videos/live`), vídeo, live, playlist ou uma pasta local.
- **Busca inteligente nas legendas**: ignora acentos e maiúsculas ("Bárbara" = "barbara"),
  aceita frases ("Ana Paula") e, opcionalmente, erros de transcrição ("Barbra", "Rucher").
- **Precisão por palavra**: usa o tempo de cada palavra das legendas automáticas do YouTube.
- **Corte só do trecho**: baixa apenas os segundos necessários (com margem antes/depois),
  em H.264/AAC, com corte no quadro exato ou cópia direta (mais rápida).
- **Arquivos locais também**: legenda ao lado do vídeo (`.vtt`/`.srt`) ou embutida no MKV/MP4;
  corte acelerado por GPU via VA-API (AMD/Intel).
- **Relatório** CSV/JSON com cada menção e link `youtu.be/…?t=` que abre no segundo certo.
- Interface Qt Quick com tema claro/escuro que segue o sistema, e CLI para automação.

## Instalação (Arch / BigLinux / Manjaro)

```bash
sudo pacman -S --needed python pyside6 yt-dlp ffmpeg nodejs   # nodejs (ou deno) resolve os desafios JS do YouTube
git clone <este-repositório> youtube-cut && cd youtube-cut
pip install --user --no-deps .                                  # instala o comando youtube-cut
install -Dm644 data/youtube-cut.desktop ~/.local/share/applications/youtube-cut.desktop
install -Dm644 data/youtube-cut.svg ~/.local/share/icons/hicolor/scalable/apps/youtube-cut.svg
```

Para rodar sem instalar: `PYTHONPATH=src python -m youtube_cut`.

## Uso

### Interface gráfica

```bash
youtube-cut
```

1. Cole o link do canal (pode ser o do YouTube Studio) ou arraste um vídeo/pasta para a janela.
2. Digite os nomes, separados por vírgula, e pressione **Enter**.
3. Revise os trechos (clique no tempo para assistir no YouTube naquele segundo), desmarque o que
   não quiser e clique em **Cortar** (`Ctrl+Enter`).

Trocar os termos depois da primeira busca é instantâneo: as legendas ficam em cache
(`~/.cache/youtube-cut`). Atalhos: `Ctrl+L` foca o link, `Ctrl+,` abre as configurações,
`Esc` cancela.

### Linha de comando

```bash
# lista as menções nas 30 lives mais recentes e salva relatório
youtube-cut scan "https://studio.youtube.com/channel/UCJZUvE04sPBhwVVuk5g9bUg/videos/live" \
    -t "Bárbara" --report barbara.csv

# corta os trechos (3 s antes, 5 s depois), tolerando erros de transcrição
youtube-cut scan @canal -t "Bárbara, Ana Paula" --fuzzy 0.2 --cut -o ~/Vídeos/cortes

# pasta local com vídeos + legendas
youtube-cut scan ~/Gravações -t Bárbara --cut --hwaccel vaapi
```

`youtube-cut scan --help` mostra todas as opções. As flags valem só para a execução; as
preferências da interface ficam em `~/.config/youtube-cut/settings.json`.

### Vídeos privados ou "confirme que você não é um robô"

Em **Configurações → Usar login do navegador** (ou `--cookies firefox`), o yt-dlp lê os
cookies da sessão já logada no seu navegador, localmente. Nada é enviado a terceiros.

## Desenvolvimento

```bash
python -m venv --system-site-packages .venv && .venv/bin/pip install yt-dlp pytest
.venv/bin/python -m pytest              # testes offline (GUI roda em modo offscreen)
.venv/bin/python -m pytest --run-network  # inclui o teste contra o YouTube real
```

Documentação técnica em [`docs/`](docs/):
[arquitetura](docs/01-arquitetura.md) ·
[design e UX](docs/02-design-ux.md) ·
[integração com o YouTube](docs/03-youtube.md) ·
[pipeline de corte](docs/04-pipeline-corte.md) ·
[instalação e testes](docs/05-instalacao-testes.md).

## Limitações

- Depende das legendas do YouTube. Lives muito longas ou recentes podem ainda não ter
  transcrição automática; vídeos sem legenda aparecem como "Sem legenda".
- A transcrição automática erra nomes próprios: use a tolerância a erros ou várias grafias
  (`-t "Bárbara, Barbra"`).
- Lives em andamento e agendadas são ignoradas.

## Licença

GPL-3.0-or-later. Ícones de interface no estilo [Lucide](https://lucide.dev) (ISC).
