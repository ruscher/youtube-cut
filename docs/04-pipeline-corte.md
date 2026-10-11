# 04 — Pipeline de legendas, busca e corte

## 1. Legenda → palavras (`core/subtitles.py`)

As legendas automáticas do YouTube têm um formato "rolante": cada cue repete a linha anterior
e a linha nova traz o tempo de cada palavra:

```
00:05:43.000 --> 00:05:44.600
beleza?<00:05:44.600><c> Aqui</c><00:05:44.759><c> é</c><00:05:44.840><c> Rafael</c>
```

- Com marcações inline, usamos **só a última linha** de cada cue, ignorando repetições e cues
  de transição de 10 ms. Cada palavra termina onde a próxima começa; a última tem no máximo
  0,8 s.
- Sem marcações (legenda manual, SRT), as palavras são distribuídas dentro do bloco
  proporcionalmente ao tamanho. Blocos idênticos consecutivos são deduplicados.
- Tags (`<i>`, `<c>`, `<v>`) e entidades (`&gt;`) são removidas; arquivos em CP-1252/Latin-1
  também são aceitos.

## 2. Busca (`core/search.py`)

- `normalize`: decomposição NFKD, remove diacríticos, `casefold`, tira pontuação.
  "Bárbara," → `barbara`.
- Termos com várias palavras casam com palavras consecutivas.
- **Tolerância** (`fuzzy`): semelhança `SequenceMatcher.ratio() ≥ 1 − fuzzy`, só para termos
  com 4+ letras (abaixo disso, os falsos positivos explodem).
- **Desempenho**: a semelhança é calculada uma vez por palavra **distinta** da transcrição,
  e não por ocorrência, com descarte prévio por tamanho e por `real_quick_ratio`/`quick_ratio`.
  Uma live de 5 h (55 mil palavras, 3 termos) caiu de 1,40 s para 0,09 s.
  `test_optimized_fuzzy_matches_brute_force` garante o mesmo resultado da força bruta.

## 3. Trechos (`core/clips.py`)

`build_clips(matches, before=3, after=5, duration, merge_gap=1)`:

- `[início − before, fim + after]`, limitado a `[0, duração]`;
- ocorrências do mesmo vídeo que se sobrepõem, ou distam menos de `merge_gap`, viram um trecho
  só ("2 menções juntas").

## 4. Corte

### YouTube

Ver [03-youtube.md](03-youtube.md#download-de-trechos).

### Arquivo local (`core/ffmpeg.py`)

```
ffmpeg -ss INÍCIO -i entrada -t DURAÇÃO -map 0:v:0? -map 0:a:0? <codec> -movflags +faststart saída.mp4
```

- **Preciso + VA-API** (`hwaccel=auto` e `/dev/dri/renderD128` com `h264_vaapi`):
  `-vaapi_device … -vf format=nv12,hwupload -c:v h264_vaapi -qp 22`. Se falhar, repete
  automaticamente na CPU (`libx264`).
- **Rápido**: `-c copy -avoid_negative_ts make_zero`.
- Progresso via `-progress pipe:1` (`out_time_us`). O cancelamento é vigiado por uma thread
  que encerra o FFmpeg em até 50 ms e apaga o arquivo parcial.
- A legenda local é procurada ao lado do vídeo (`nome*.vtt|srt`, com escape de `[]*?`) ou
  extraída da primeira faixa embutida.

## 5. Saída

`<pasta de saída>/<termos>/<AAAA-MM-DD> <título> - 01h02m03s.mp4`. Emojis e caracteres
inválidos são removidos e o título é limitado a 60 caracteres.
O relatório CSV/JSON traz vídeo, termo, texto dito, início, fim, contexto, similaridade e
link com `?t=`.
