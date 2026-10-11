# 01 — Arquitetura

## Visão geral

```
            ┌──────────── interface ────────────┐      ┌─── CLI ───┐
            │ QML (Main.qml + componentes)      │      │  cli.py   │
            │        ▲ propriedades/sinais      │      └─────┬─────┘
            │ gui/backend.py  gui/models.py     │            │
            └──────────────┬────────────────────┘            │
                           ▼                                 ▼
                 core/pipeline.py  (descobrir → legendas → buscar → trechos → cortar)
          ┌──────────┬──────────────┬─────────────┬──────────────┬─────────────┐
          ▼          ▼              ▼             ▼              ▼             ▼
   core/youtube  core/subtitles  core/search   core/clips    core/ffmpeg   core/config
    (yt-dlp)     (VTT/SRT →      (sem acento,  (margem e     (corte local, (XDG,
                  palavras)       fuzzy)        fusão)        VA-API)       settings)
```

- **`core/` não importa Qt.** A CLI e a interface usam exatamente o mesmo `Pipeline`, e o
  núcleo é testável sem tela.
- **`Pipeline`** é quase sem estado: recebe `Settings`, um callback de log e um
  `threading.Event` de cancelamento. Os resultados (`VideoResult`) guardam as palavras
  carregadas para que uma nova busca não acesse a rede.

## Fluxo de dados

1. `discover(fonte)` → `resolve_source` normaliza o link (Studio, canal, `@handle`, vídeo,
   playlist) ou detecta caminho local / `file://` → lista de `VideoResult`.
2. `scan(result, termos)` → `load_words` baixa (ou lê do cache) **uma** faixa de legenda e
   converte em `list[Word]` (início, fim, texto) → `find_matches` → `list[Match]`.
3. `clips_for(result)` → `build_clips` aplica margens, limita à duração e funde trechos
   próximos → `list[Clip]`.
4. `cut(video, clip, saída)` → `YouTubeClient.download_clip` (só o intervalo, via yt-dlp
   + FFmpeg) ou `ffmpeg.cut_local`.

## Concorrência na interface

O trabalho pesado roda em `threading.Thread`; o resultado volta para a thread da interface
por sinais Qt privados do `Backend` (`_discovered`, `_videoUpdated`, `_clipUpdated`…),
entregues de forma enfileirada. Como um sinal pode chegar depois de o worker já ter avançado,
`_on_video_updated` **compara** os trechos esperados com os existentes (por
`(vídeo, início, fim)`) em vez de só acrescentar. Assim, processar o mesmo sinal duas vezes
não duplica nada. `_rebuild_clips` preserva a seleção e o estado de corte dos trechos que
não mudaram.

## Por que não Playwright + YouTube Studio?

A proposta original automatizava o navegador no Studio. Foi descartada porque:

- os seletores do Studio (`ytcp-video-row`…) mudam sem aviso;
- o Chrome trava o perfil em uso (`~/.config/google-chrome`) e o Google bloqueia logins
  automatizados (`AutomationControlled`);
- o Studio não oferece as legendas automáticas com tempo por palavra.

O yt-dlp entrega a lista do canal, as legendas e o download de intervalos com uma API
estável. Os cookies do navegador cobrem os vídeos privados sem automatizar login.

## Estrutura

```
src/youtube_cut/
  cli.py                 argparse; sem argumentos abre a GUI
  core/                  lógica pura (ver diagrama)
  gui/app.py             QApplication, estilo Basic, provedor de ícones, carga do QML
  gui/backend.py         QObject exposto como `backend` ao QML
  gui/models.py          VideoListModel, ClipListModel (QAbstractListModel)
  gui/icons.py           ícones SVG coloridos pelo tema (image://icon/nome/cor)
  gui/qml/               Theme (singleton), Main e componentes
tests/                   pytest; GUI em QT_QPA_PLATFORM=offscreen
data/                    .desktop e ícone
```
