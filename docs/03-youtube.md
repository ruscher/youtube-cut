# 03 — Integração com o YouTube (`core/youtube.py`)

## Links aceitos (`resolve_source`)

| Entrada | Vira |
|---|---|
| `studio.youtube.com/channel/UC…/videos/live` | `youtube.com/channel/UC…/streams` |
| `studio.youtube.com/channel/UC…/videos/upload` | `…/videos` (e `short` → `…/shorts`) |
| `studio.youtube.com/video/ID/edit` | `watch?v=ID` |
| `UC…` (ID de canal), `@handle`, `youtube.com/@x[/aba]` | canal na aba configurada (padrão: lives) |
| `youtu.be/ID`, `watch?v=ID`, `/live/ID`, `/shorts/ID`, ID de 11 caracteres | vídeo |
| `playlist?list=…` | playlist |

## Listagem

`extract_info(..., extract_flat="in_playlist", playlistend=N)`: uma única requisição traz
ID, título, duração e `live_status`. Lives agendadas ou em andamento são ignoradas, porque
ainda não têm transcrição.

## Legendas: uma faixa por vídeo

Baixar todas as faixas (como em `--sub-langs "pt.*"`) provoca **HTTP 429** rapidamente; isso
aconteceu nos testes reais. Por isso `_choose_track` escolhe só uma:

1. legenda **manual** no idioma (`pt`, depois `pt-BR`, `pt-PT`…);
2. transcrição automática **original** `pt-orig`, que traz o tempo por palavra;
3. a original de outro idioma (`en-orig`…), já que nomes próprios aparecem nela;
4. só então uma tradução automática para o idioma.

Proteções:

- **Cache em disco** (`~/.cache/youtube-cut/subtitles/ID.pt.auto.vtt`) e marcador `.none`
  por 24 h para vídeos sem legenda. Repetir uma busca não consulta o YouTube.
- **Espaçamento** mínimo de 1,5 s entre consultas (`_throttle`).
- **429 com recuo**: novas tentativas após 4, 12, 30 e 60 s, avisando na barra de status.

## Download de trechos

`download_ranges=download_range_func(None, [(início, fim)])` faz o yt-dlp invocar o FFmpeg
com `-ss/-t` direto nas URLs do googlevideo: só os segundos pedidos trafegam. Formato
preferido: `bv*[height<=Q][vcodec^=avc1]+ba[ext=m4a]`, que abre em qualquer editor.

- **Corte preciso** (`force_keyframes_at_cuts`): o trecho é reencodado
  (`libx264 veryfast crf 20`, AAC 160k, `+faststart`) e começa no quadro exato.
- **Rápido**: cópia direta; pode começar no keyframe anterior.
- O googlevideo às vezes recusa a conexão no meio do trecho (FFmpeg sai com código 8). Uma
  nova extração gera URLs novas: são feitas até 3 tentativas (espera de 3 s e 10 s).

## Ambiente do yt-dlp

- `js_runtimes`: habilita `deno`, `node` ou `bun`, os que estiverem no PATH. O YouTube exige
  um runtime JS para resolver os desafios de assinatura.
- `remote_components=["ejs:github"]` só se o usuário permitir. O ideal é instalar `yt-dlp-ejs`.
- `cookiesfrombrowser`: quando configurado, lê os cookies do navegador localmente.
- Mensagens de erro do yt-dlp são traduzidas em orientações (`_friendly_error`).
