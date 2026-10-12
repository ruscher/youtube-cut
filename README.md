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
- **Legenda por IA**: vídeo sem legenda? O áudio é transcrito no computador com Whisper
  (whisper.cpp ou faster-whisper), com tempo por palavra, e a busca funciona igual.
- **Reconhecimento facial**: a partir de fotos de uma pessoa, encontra os momentos em que ela
  aparece no vídeo e corta esses trechos, junto ou no lugar das menções faladas.
- Interface Qt Quick com tema claro/escuro que segue o sistema, e CLI para automação.

## Instalação (Arch / BigLinux / Manjaro)

```bash
git clone <este-repositório> youtube-cut
cd youtube-cut/packaging/arch
makepkg -si          # instala dependências, gera e instala o pacote youtube-cut
```

O pacote coloca o comando `youtube-cut`, o atalho no menu e o ícone. Para remover:
`sudo pacman -R youtube-cut`. Recomendado: `sudo pacman -S --needed nodejs` (ou `deno`),
o runtime JS que o YouTube exige para liberar os downloads.

Recursos de IA local (opcionais): `sudo pacman -S --needed python-opencv` para o
reconhecimento facial e `sudo pacman -S --needed whisper-cpp` para gerar legendas.

Para rodar sem instalar, a partir da raiz do repositório:

```bash
sudo pacman -S --needed pyside6 yt-dlp ffmpeg nodejs
PYTHONPATH=src python -m youtube_cut            # interface
PYTHONPATH=src python -m youtube_cut scan --help
```

> `pip install --user` não funciona no Arch e derivados (PEP 668, "externally-managed-environment").
> Use o PKGBUILD acima ou um ambiente virtual (ver [Desenvolvimento](#desenvolvimento)).

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

### IA local: legenda por Whisper e reconhecimento facial

Abra o painel **IA local** (`Ctrl+I`):

- **Reconhecimento facial**: arraste de 1 a 5 fotos nítidas da pessoa, de frente. Com
  "Procurar este rosto ao buscar" ligado, cada vídeo também é analisado quadro a quadro, e os
  trechos em que ela aparece entram na lista ("Rosto · 88%"). Os termos ficam opcionais: dá
  para buscar só pelo rosto. Lives do YouTube são lidas em 360p, sem salvar o vídeo.
- **Legenda por IA**: com "Gerar legenda quando o vídeo não tiver" ligado, vídeos sem
  legenda são transcritos no computador. Também dá para gerar a de um vídeo só, pelo botão
  **Gerar legenda** na lista. O modelo `small` equilibra precisão e tempo.
- **Atividade**: o console mostra cada etapa (download de modelos, transcrição, varredura).

Na linha de comando:

```bash
youtube-cut scan ~/Gravações --face barbara.jpg --face-label Bárbara --face-json barbara.json --cut
youtube-cut scan @canal -t Bárbara --whisper --whisper-model small
```

Tudo roda no seu computador. Rosto é dado biométrico sensível (LGPD): use em gravações
próprias ou com autorização das pessoas. Detalhes em [IA local](docs/06-ia-local.md).

## Desenvolvimento

```bash
python -m venv --system-site-packages .venv && .venv/bin/pip install yt-dlp pytest
.venv/bin/python -m pytest              # testes offline (GUI roda em modo offscreen)
.venv/bin/python -m pytest --run-network  # inclui o teste contra o YouTube real
.venv/bin/pip install faster-whisper      # opcional: motor de legenda por IA no venv
```

Documentação técnica em [`docs/`](docs/):
[arquitetura](docs/01-arquitetura.md) ·
[design e UX](docs/02-design-ux.md) ·
[integração com o YouTube](docs/03-youtube.md) ·
[pipeline de corte](docs/04-pipeline-corte.md) ·
[instalação e testes](docs/05-instalacao-testes.md) ·
[IA local](docs/06-ia-local.md).

## Limitações

- Depende das legendas do YouTube. Lives muito longas ou recentes podem ainda não ter
  transcrição automática; sem a legenda por IA, esses vídeos aparecem como "Sem legenda".
- O reconhecimento facial não reconhece rostos de perfil, cobertos ou muito pequenos no
  quadro, e analisar lives do YouTube transfere o vídeo em 360p (~150–250 MB por hora).
- A transcrição automática erra nomes próprios: use a tolerância a erros ou várias grafias
  (`-t "Bárbara, Barbra"`).
- Lives em andamento e agendadas são ignoradas.

## Licença

GPL-3.0-or-later. Ícones de interface no estilo [Lucide](https://lucide.dev) (ISC).
