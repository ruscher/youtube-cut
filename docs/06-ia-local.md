# 06 — IA local: legenda por Whisper e reconhecimento facial

Dois recursos opcionais, ambos executados no computador do usuário:

- **Legenda por IA**: quando o vídeo não tem legenda, o áudio é transcrito com Whisper e a
  busca de termos funciona como sempre, com tempo por palavra.
- **Reconhecimento facial**: a partir de fotos de uma pessoa, marca os momentos em que ela
  aparece no vídeo; esses momentos viram trechos de corte como as menções faladas.

Nenhum dos dois é obrigatório. Sem as bibliotecas, o app funciona como antes e o painel
**IA local** (`Ctrl+I`) explica o que instalar.

## Onde se encaixam

```
core/pipeline.py   scan(resultado, termos)
   │
   ├─ load_words ── legenda do YouTube / arquivo / embutida
   │                 └─ sem legenda e fallback ligado ──► core/subtitles_fallback.py
   │                                                       (faster-whisper | whisper.cpp)
   ├─ search ────── find_matches (fala)  +  face_matches (rosto), na ordem do vídeo
   └─ scan_faces ── só se face_enabled e houver fotos ───► core/face_detector.py
                                                          (OpenCV YuNet + SFace)
core/download.py   modelos baixados uma vez, conferidos por SHA-256
```

- Um trecho de rosto é um `Match` com `kind="face"`, `term="Rosto: <nome>"` e a
  similaridade em `score`. Por isso `build_clips` (margens e fusão), o corte, o relatório
  (coluna `tipo`) e a interface funcionam sem caminhos paralelos. Uma menção dita enquanto
  a pessoa aparece é fundida no mesmo trecho.
- `VideoResult.face_matches` guarda os trechos de rosto à parte: refazer a busca de texto
  (`search`) não apaga o que a varredura de rostos encontrou.
- Novos estados de vídeo: `transcribing` e `faces`, com `progress` (0–1, ou −1 sem medida).
  O pipeline avisa a interface por `on_change`, no máximo 4 vezes por segundo.

## Legenda por IA (`core/subtitles_fallback.py`)

**Motores**, nesta ordem:

| Motor | Instalação | Tempo por palavra |
|---|---|---|
| faster-whisper (CTranslate2) | `pip install faster-whisper` (não está nos repositórios do Arch) | nativo (`word_timestamps`) |
| whisper.cpp | `sudo pacman -S whisper-cpp` (`whisper-cli`) ou `whisper.cpp` do BigLinux | `-ml 1 -sow`: um segmento por palavra |

- **Por que não pedir a legenda ao YouTube Studio:** o Studio não tem uma ação para "gerar a
  transcrição automática"; ela aparece quando o YouTube consegue gerá-la. Automatizar o
  navegador foi descartado em [01-arquitetura](01-arquitetura.md).
- **Áudio:** de vídeos do YouTube, só o áudio é baixado (~50 kbps, apagado depois da
  transcrição). O FFmpeg decodifica para 16 kHz mono float32; o decodificador do
  faster-whisper (PyAV) não é usado porque o PyAV do Arch quebra a chamada dele
  (`metadata_errors`). Uma hora de áudio ocupa ~230 MB de memória durante a transcrição.
- **GPU:** o faster-whisper tenta CUDA e cai para CPU (int8) em qualquer falha da GPU, com
  o motivo no console. O CTranslate2 do pip é compilado para CUDA 12 (`libcublas.so.12`):
  com o pacote `cuda` 13 do Arch ele roda na CPU, e o painel diz isso.
- **Modelos:** faster-whisper baixa do Hugging Face para `~/.cache/youtube-cut/models`.
  O whisper.cpp usa primeiro os pacotes do BigLinux (`/usr/share/whisper.cpp-model-<m>/`);
  senão baixa `ggml-<m>.bin` conferindo o SHA-256 publicado no ponteiro Git LFS.
- **Cache:** o resultado é salvo como `subtitles/<id>.<idioma>.whisper-<modelo>.vtt`, no
  formato das legendas automáticas do YouTube (`<00:00:01.400><c> palavra</c>`), que o
  `subtitles.py` já lê com tempo por palavra. Repetir a busca não transcreve de novo.

## Reconhecimento facial (`core/face_detector.py`)

1. **Referência:** em cada foto, o **YuNet** acha o maior rosto e o **SFace** gera um vetor
   de 128 dimensões do rosto alinhado. A referência é a média normalizada (várias fotos da
   mesma pessoa deixam a comparação mais robusta).
2. **Amostragem:** o FFmpeg decodifica direto para um pipe, já em `fps` quadros por segundo
   e em 640×360 com tarja. Nada vai para o disco.
3. **Comparação:** similaridade de cosseno entre cada rosto do quadro e a referência.
   Limiares: rigoroso 0,45 · normal 0,38 · flexível 0,32 (o SFace indica 0,363).
4. **Blocos:** amostras positivas consecutivas viram intervalos (`±½` amostra), lacunas de
   até 2 amostras não quebram o bloco, e blocos com menos de 1 s são descartados.

- **Por que OpenCV e não dlib/InsightFace/YOLOv8:** YuNet e SFace já vêm no `python-opencv`
  dos repositórios oficiais e são modelos ONNX pequenos (0,2 MB + 38,7 MB, conferidos por
  SHA-256). dlib, InsightFace (onnxruntime) e ultralytics (torch) não estão nos repositórios
  e trariam centenas de MB.
- **Por que sem multiprocessing:** o FFmpeg já decodifica em outro processo, em paralelo com
  a análise, e a inferência do OpenCV usa todos os núcleos. Vários processos Python
  duplicariam os modelos na memória e complicariam o cancelamento, sem ganho medido.
- **Vídeos do YouTube:** o stream só de vídeo em ≤360p é lido pelo FFmpeg com os cabeçalhos
  que o yt-dlp fornece (sem salvar o arquivo, mas transferindo ~150–250 MB por hora de live).
  Se a URL expirar ou cair, a leitura recomeça do último segundo analisado com uma URL nova
  (até 3 vezes).
- **Cache:** `faces/<id>.<referência>.<fps>fps.<limiar>.json`. Trocar as fotos muda a
  impressão digital da referência e invalida o cache automaticamente.
- **Saída:** `face_detector.to_json` e `youtube-cut scan --face-json` produzem
  `[{"start": "00:01:23", "end": "00:01:45", "start_seconds": …, "end_seconds": …, "similarity": …}]`.

## Interface

- **Painel IA local** (`AiDrawer.qml`, `Ctrl+I`): arrastar ou escolher fotos (retrato redondo
  gerado em PNG pelo núcleo, sem efeitos gráficos que o renderizador por software não tem),
  nome, "procurar este rosto ao buscar", rigor, amostragem com estimativa de tempo, botão para
  procurar nos vídeos já carregados; motores de transcrição detectados, alternância do fallback,
  modelo; console de atividade com hora, copiar e limpar.
- **Lista de vídeos:** "Gerando legenda… 42%", "Procurando rosto… 42%"; vídeo sem legenda ganha
  o botão **Gerar legenda** quando há motor instalado; chips separados para menções e rosto.
- **Trechos:** chip "Rosto · 88%" (similaridade com a foto), sem as reticências de fala.
- **Busca só pelo rosto:** com o rosto ativo, os termos ficam opcionais e o botão vira
  "Buscar rosto".
- Cada execução usa uma cópia das configurações: com foto inválida, a busca segue só pelas
  legendas em vez de marcar todos os vídeos com erro.

## Linha de comando

```bash
youtube-cut scan ~/Gravações --face barbara1.jpg --face barbara2.jpg --face-label Bárbara \
    --face-json barbara.json --cut
youtube-cut scan @canal -t Bárbara --whisper --whisper-model small
```

`--face-sensitivity strict|normal|loose`, `--face-fps 0.5|1|2`. Os cortes do rosto vão para a
pasta `rosto <nome>`.

## Desempenho medido

Intel Core i7-7700HQ (4 núcleos/8 threads), CPU apenas (a GTX 1050 Ti não foi usada: falta
a `libcublas.so.12`), Python 3.14, OpenCV 5.0, faster-whisper 1.2.1, whisper.cpp 1.9.3:

| Etapa | Medida |
|---|---|
| Rosto: decodificação + detecção + reconhecimento | ~23 ms por quadro → ~1,5 min por hora de vídeo a 1 quadro/s |
| Rosto: vídeo de teste (Lena 0–4 s, Messi 4–8 s, Lena 8–12 s) | blocos 0–3,75 s e 7,75–11,75 s; Messi rejeitado (similaridade 0,13 contra 0,91) |
| faster-whisper `base`, 13 s de fala | 2,8–3,9 s (inclui carregar o modelo e a tentativa de CUDA) |
| faster-whisper `small`, 13 s de fala | 5,4 s (idem) |
| whisper.cpp `base`, 13 s de fala | 2,0 s |

Trechos curtos medem sobretudo o carregamento do modelo; o tempo por hora de áudio não foi
medido.

## Limitações

- A precisão do Whisper com **nomes próprios** não foi medida com fala humana: os testes
  usaram voz sintética (espeak-ng), que nenhum modelo transcreveu como "Bárbara". Use a
  tolerância a erros ou várias grafias, como com as legendas do YouTube.
- Rostos de perfil, cobertos ou muito pequenos no quadro (menos de 24 px em 640×360) não são
  reconhecidos. Em lives com câmera aberta, prefira amostragem de 1/s ou 2/s.
- A varredura facial de lives do YouTube depende da rede; a de arquivos locais, não.
- **Privacidade:** o reconhecimento roda só no computador e nada é enviado. Mesmo assim, rosto
  é dado biométrico sensível pela LGPD: use em gravações próprias ou com autorização das
  pessoas.
