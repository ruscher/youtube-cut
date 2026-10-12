"""Legenda de reserva: transcrição local quando o vídeo não tem legenda.

Quando o YouTube não oferece legenda (live recente, vídeo sem transcrição
automática) ou o arquivo local não tem uma, o áudio é transcrito no próprio
computador e o resultado vira uma lista de :class:`Word`, a mesma estrutura
que as legendas do YouTube produzem. Busca, trechos e cortes seguem iguais.

Dois motores, nesta ordem de preferência:

* **faster-whisper** (CTranslate2): tempo nativo por palavra; usa CUDA quando
  disponível e cai para CPU (int8) sozinho.
* **whisper.cpp** (``whisper-cli`` do pacote ``whisper-cpp`` do Arch, ou
  ``whisper.cpp`` do BigLinux): segmentos de uma palavra (``-ml 1 -sow``).

Não automatizamos o YouTube Studio para "pedir" a legenda: o Studio não tem
essa ação (a transcrição automática é gerada pelo YouTube quando ele consegue)
e a automação do navegador foi descartada pelos motivos em docs/01.

O resultado fica em cache como WebVTT no formato das legendas automáticas do
YouTube (tempo por palavra), que o :mod:`.subtitles` já sabe ler.
"""

from __future__ import annotations

import functools
import os
import re
import shutil
import subprocess
import tempfile
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from . import download
from .models import Word
from .timefmt import format_timestamp, parse_timestamp
from .youtube import Cancelled

MODELS = ("tiny", "base", "small", "medium")
DEFAULT_MODEL = "small"

# Modelos ggml do whisper.cpp: o ponteiro Git LFS em /raw/ traz o SHA-256 do arquivo.
_GGML_URL = "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-{model}.bin"
_GGML_POINTER = "https://huggingface.co/ggerganov/whisper.cpp/raw/main/ggml-{model}.bin"
_GGML_SYSTEM_DIRS = ("/usr/share/whisper.cpp-model-{model}", "/usr/share/whisper.cpp/models",
                     "/usr/share/whisper-cpp/models")
_WHISPER_CPP_BINARIES = ("whisper-cli", "whisper.cpp")
_CUDA_HINTS = ("cuda", "cublas", "cudnn", "libcu")
_PROGRESS = re.compile(r"progress\s*=\s*(\d+)%")
_TIMING = re.compile(r"^((?:\d+:)?\d{1,2}:\d{2}\.\d{3})\s*-->\s*((?:\d+:)?\d{1,2}:\d{2}\.\d{3})")

Log = Callable[[str], None]
Progress = Callable[[float], None]


class TranscriptionError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class EngineInfo:
    name: str  # faster-whisper | whisper.cpp
    available: bool
    detail: str  # para a interface: versão/dispositivo ou como instalar


# -- descoberta dos motores -----------------------------------------------

def _faster_whisper_info() -> EngineInfo:
    try:
        import ctranslate2
        import faster_whisper
    except ImportError:
        return EngineInfo("faster-whisper", False, "não instalado (pip install faster-whisper)")
    try:
        gpus = ctranslate2.get_cuda_device_count()
    except Exception:  # noqa: BLE001 - bibliotecas CUDA ausentes não são erro aqui
        gpus = 0
    if gpus and _cuda_runtime_loadable():
        device = "CUDA"
    elif gpus:
        # ex.: Arch com cuda 13 instalado, mas o CTranslate2 do pip compilado para CUDA 12
        device = "CPU (GPU encontrada, mas sem a libcublas do CUDA 12 usada pelo CTranslate2)"
    else:
        device = "CPU"
    version = getattr(faster_whisper, "__version__", "")
    return EngineInfo("faster-whisper", True, f"{version} · {device}".strip(" ·"))


def _cuda_runtime_loadable() -> bool:
    """CTranslate2 4.x usa cuBLAS do CUDA 12; sem ele a GPU falharia na primeira inferência."""
    import ctypes

    try:
        ctypes.CDLL("libcublas.so.12")
    except OSError:
        return False
    return True


def _whisper_cpp_binary() -> str | None:
    return next((p for b in _WHISPER_CPP_BINARIES if (p := shutil.which(b))), None)


def _whisper_cpp_info() -> EngineInfo:
    binary = _whisper_cpp_binary()
    if not binary:
        return EngineInfo("whisper.cpp", False, "não instalado (sudo pacman -S whisper-cpp)")
    return EngineInfo("whisper.cpp", True, Path(binary).name)


def engines() -> list[EngineInfo]:
    """Situação de cada motor, na ordem de preferência."""
    return [_faster_whisper_info(), _whisper_cpp_info()]


def pick_engine(preferred: str = "auto") -> str | None:
    available = [e.name for e in engines() if e.available]
    if preferred in available:
        return preferred
    return available[0] if available else None


# -- saída ----------------------------------------------------------------

def words_to_vtt(words: list[Word], per_cue: int = 10) -> str:
    """WebVTT com tempo por palavra, no formato das legendas automáticas do YouTube.

    Cada cue traz até ``per_cue`` palavras: a primeira começa no início do cue e
    as demais levam ``<hh:mm:ss.mmm><c> palavra</c>``, de modo que
    :func:`.subtitles.parse_subtitle_text` recupera o início de cada palavra.
    """
    out = ["WEBVTT", "Kind: captions", ""]
    for i in range(0, len(words), per_cue):
        chunk = words[i:i + per_cue]
        line = chunk[0].text + "".join(
            f"<{format_timestamp(w.start)}><c> {w.text}</c>" for w in chunk[1:]
        )
        out += [f"{format_timestamp(chunk[0].start)} --> {format_timestamp(chunk[-1].end)}", line, ""]
    return "\n".join(out)


def cache_path(cache_dir: Path, video_id: str, language: str, model: str) -> Path:
    return cache_dir / f"{video_id}.{language}.whisper-{model}.vtt"


# -- transcrição ----------------------------------------------------------

def transcribe(
    media: Path,
    language: str = "pt",
    model: str = DEFAULT_MODEL,
    engine: str = "auto",
    models_dir: Path | None = None,
    log: Log | None = None,
    cancel: threading.Event | None = None,
    progress: Progress | None = None,
) -> list[Word]:
    """Transcreve o áudio de ``media`` (áudio ou vídeo) e retorna as palavras."""
    if model not in MODELS:
        raise TranscriptionError(f"Modelo desconhecido: {model}. Use um de: {', '.join(MODELS)}.")
    name = pick_engine(engine)
    if name is None:
        raise TranscriptionError(
            "Nenhum motor de transcrição instalado. Instale o whisper.cpp "
            "(sudo pacman -S whisper-cpp) ou o faster-whisper (pip install faster-whisper)."
        )
    log = log or (lambda _m: None)
    cancel = cancel or threading.Event()
    models_dir = models_dir or Path(tempfile.gettempdir()) / "youtube-cut-models"
    if name == "faster-whisper":
        return _faster_whisper(media, language, model, models_dir, log, cancel, progress)
    return _whisper_cpp(media, language, model, models_dir, log, cancel, progress)


# faster-whisper ----------------------------------------------------------

@functools.cache
def _fw_model(model: str, device: str, models_dir: str):
    from faster_whisper import WhisperModel

    # "auto" na GPU: placas antigas (Pascal, ex. GTX 10xx) não têm float16 eficiente.
    compute = "auto" if device == "cuda" else "int8"
    return WhisperModel(model, device=device, compute_type=compute, download_root=models_dir)


def _faster_whisper(media, language, model, models_dir, log, cancel, progress) -> list[Word]:
    import ctranslate2

    try:
        devices = ["cuda", "cpu"] if ctranslate2.get_cuda_device_count() > 0 else ["cpu"]
    except Exception:  # noqa: BLE001
        devices = ["cpu"]
    audio = decode_audio(media, cancel)
    if audio.size == 0:
        return []
    for device in devices:
        log(f"Transcrevendo com faster-whisper ({model}, {device.upper()})…")
        try:
            whisper = _fw_model(model, device, str(models_dir / "faster-whisper"))
            return _fw_run(whisper, audio, language, cancel, progress)
        except Cancelled:
            raise
        except Exception as e:
            # Sem cuBLAS/cuDNN, ou com GPU sem suporte, a falha só aparece na
            # primeira inferência: qualquer erro na GPU tenta de novo na CPU.
            if device == "cuda":
                hint = " (bibliotecas CUDA ausentes)" if any(h in str(e).lower() for h in _CUDA_HINTS) else ""
                log(f"A GPU não pôde ser usada{hint}; continuando na CPU. Detalhe: {str(e)[:160]}")
                continue
            raise TranscriptionError(f"faster-whisper falhou: {e}") from e
    raise AssertionError("unreachable")


SAMPLE_RATE = 16000


def decode_audio(media: Path, cancel: threading.Event):
    """Áudio mono 16 kHz em float32 (numpy), decodificado pelo FFmpeg.

    Não usamos o decodificador do faster-whisper (PyAV): versões novas do PyAV,
    como a do Arch, quebram a chamada dele. O FFmpeg já é dependência do app.
    Uma hora de áudio ocupa ~230 MB de memória durante a transcrição.
    """
    import numpy as np

    cmd = ["ffmpeg", "-v", "error", "-nostdin", "-i", str(media), "-vn", "-ac", "1",
           "-ar", str(SAMPLE_RATE), "-f", "f32le", "pipe:1"]
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except OSError as e:
        raise TranscriptionError(f"FFmpeg não encontrado: {e}") from e
    errors: list[bytes] = []
    reader = threading.Thread(target=lambda: errors.append(proc.stderr.read()), daemon=True)
    reader.start()
    chunks = []
    while block := proc.stdout.read(1 << 20):
        if cancel.is_set():
            # fechar o pipe antes de esperar: com SIGTERM o FFmpeg tenta terminar de escrever
            proc.terminate()
            proc.stdout.close()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
            raise Cancelled()
        chunks.append(block)
    proc.wait()
    reader.join(timeout=2)
    if proc.returncode != 0:
        detail = b"".join(errors).decode("utf-8", "replace").strip()[-300:]
        raise TranscriptionError(f"FFmpeg não conseguiu ler o áudio: {detail}")
    data = b"".join(chunks)
    return np.frombuffer(data[: len(data) // 4 * 4], dtype=np.float32)


def _fw_run(whisper, audio, language, cancel, progress) -> list[Word]:
    segments, info = whisper.transcribe(
        audio, language=language or None, word_timestamps=True, vad_filter=True,
    )
    duration = getattr(info, "duration", 0) or 0
    words: list[Word] = []
    for segment in segments:  # gerador: a transcrição avança a cada iteração
        if cancel.is_set():
            raise Cancelled()
        for w in segment.words or []:
            text = w.word.strip()
            if text:
                words.append(Word(round(w.start, 3), round(max(w.end, w.start), 3), text))
        if progress and duration:
            progress(min(1.0, float(segment.end) / float(duration)))
    return words


# whisper.cpp -------------------------------------------------------------

def _ggml_model(model: str, models_dir: Path, log: Log, cancel, progress) -> Path:
    for folder in _GGML_SYSTEM_DIRS:
        candidate = Path(folder.format(model=model)) / f"ggml-{model}.bin"
        if candidate.is_file():
            return candidate
    dest = models_dir / "whisper.cpp" / f"ggml-{model}.bin"
    if dest.is_file():
        return dest
    log(f"Baixando o modelo {model} do whisper.cpp (uma vez só)…")
    sha256 = _ggml_sha256(model)
    return download.fetch(_GGML_URL.format(model=model), dest, sha256, progress=progress, cancel=cancel)


def _ggml_sha256(model: str) -> str | None:
    """SHA-256 publicado no ponteiro Git LFS do Hugging Face (None se indisponível)."""
    import urllib.request

    try:
        with urllib.request.urlopen(_GGML_POINTER.format(model=model), timeout=15) as r:
            text = r.read(1024).decode("ascii", "replace")
    except OSError:
        return None
    m = re.search(r"oid sha256:([0-9a-f]{64})", text)
    return m.group(1) if m else None


def _whisper_cpp(media, language, model, models_dir, log, cancel, progress) -> list[Word]:
    binary = _whisper_cpp_binary()
    model_path = _ggml_model(model, models_dir, log, cancel, None)
    with tempfile.TemporaryDirectory(prefix="youtube-cut-") as tmp:
        wav = Path(tmp) / "audio.wav"
        _run(["ffmpeg", "-v", "error", "-nostdin", "-y", "-i", str(media), "-vn",
              "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", str(wav)], cancel, "ffmpeg")
        log(f"Transcrevendo com whisper.cpp ({model})…")
        out = Path(tmp) / "out"
        cmd = [binary, "-m", str(model_path), "-f", str(wav), "-l", language or "auto",
               "-ml", "1", "-sow", "-ovtt", "-of", str(out), "-pp",
               "-t", str(max(1, (os.cpu_count() or 4) - 1))]
        _run(cmd, cancel, "whisper.cpp", progress)
        vtt = out.with_suffix(".vtt")
        if not vtt.exists():
            raise TranscriptionError("O whisper.cpp terminou sem gerar a legenda.")
        return parse_word_cues(vtt.read_text(encoding="utf-8", errors="replace"))


def parse_word_cues(text: str) -> list[Word]:
    """Lê o VTT do whisper.cpp com ``-ml 1``: cada cue é uma palavra."""
    words: list[Word] = []
    lines = text.replace("\r\n", "\n").split("\n")
    for i, line in enumerate(lines):
        m = _TIMING.match(line.strip())
        if not m or i + 1 >= len(lines):
            continue
        token = " ".join(lines[i + 1].split())
        if token:
            start, end = parse_timestamp(m.group(1)), parse_timestamp(m.group(2))
            words.append(Word(round(start, 3), round(max(end, start), 3), token))
    return words


def _run(cmd: list[str], cancel: threading.Event, label: str, progress: Progress | None = None) -> None:
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                                text=True, errors="replace")
    except OSError as e:
        raise TranscriptionError(f"Não foi possível executar {label}: {e}") from e
    tail: list[str] = []

    def watch_cancel() -> None:
        while proc.poll() is None:
            if cancel.wait(0.1):
                proc.terminate()
                return

    threading.Thread(target=watch_cancel, daemon=True).start()
    for line in proc.stderr:
        if progress and (m := _PROGRESS.search(line)):
            progress(int(m.group(1)) / 100)
        tail = (tail + [line.rstrip()])[-8:]
    proc.wait()
    if cancel.is_set():
        raise Cancelled()
    if proc.returncode != 0:
        detail = " ".join(t for t in tail if t)[-400:]
        raise TranscriptionError(f"{label} falhou (código {proc.returncode}): {detail}")
