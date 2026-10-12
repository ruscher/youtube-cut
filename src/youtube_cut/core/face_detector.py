"""Reconhecimento facial: em que momentos uma pessoa aparece no vídeo.

Pipeline (tudo local, só OpenCV, sem dlib/torch):

1. **Referência**: em cada foto, o detector **YuNet** acha o maior rosto e o
   reconhecedor **SFace** gera um vetor de 128 dimensões do rosto alinhado. A
   referência é a média normalizada dos vetores (várias fotos = mais robusto).
2. **Amostragem**: o FFmpeg decodifica o vídeo direto para um pipe, já na
   taxa de amostragem (ex.: 1 quadro/s) e reduzido para 640×360. Nada vai para
   o disco, e a mesma rotina serve para arquivo local ou stream do YouTube.
3. **Comparação**: em cada quadro, a similaridade de cosseno entre cada rosto
   detectado e a referência. SFace considera a mesma pessoa a partir de 0,363.
4. **Blocos de tempo**: amostras positivas consecutivas viram intervalos,
   tolerando lacunas curtas (rosto virado, piscada de detecção) e descartando
   aparições curtas demais.

Os modelos ONNX oficiais do OpenCV Zoo são baixados uma vez e conferidos por
SHA-256.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import threading
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path

from . import download
from .timefmt import format_timestamp
from .youtube import Cancelled

try:
    import cv2
    import numpy as np
except ImportError:  # pragma: no cover - verificado em tempo de execução
    cv2 = None
    np = None


@dataclass(frozen=True, slots=True)
class ModelSpec:
    filename: str
    url: str
    sha256: str


_ZOO = "https://github.com/opencv/opencv_zoo/raw/main/models"
DETECTOR = ModelSpec(
    "face_detection_yunet_2023mar.onnx",
    f"{_ZOO}/face_detection_yunet/face_detection_yunet_2023mar.onnx",
    "8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4",
)
RECOGNIZER = ModelSpec(
    "face_recognition_sface_2021dec.onnx",
    f"{_ZOO}/face_recognition_sface/face_recognition_sface_2021dec.onnx",
    "0ba9fbfa01b5270c96627c4ef784da859931e02f04419c829e83484087c34e79",
)

# Limiares de similaridade de cosseno (SFace: mesma pessoa a partir de 0,363).
THRESHOLDS = {"strict": 0.45, "normal": 0.38, "loose": 0.32}
DEFAULT_THRESHOLD = THRESHOLDS["normal"]
FRAME_SIZE = (640, 360)
_MIN_DETECTION_SCORE = 0.8
_MIN_FACE_PX = 24  # rostos menores que isso no quadro reduzido não são confiáveis

Log = Callable[[str], None]
Progress = Callable[[float], None]


class FaceError(RuntimeError):
    pass


def available() -> tuple[bool, str]:
    """(disponível, detalhe para a interface)."""
    if cv2 is None:
        return False, "OpenCV não instalado (sudo pacman -S python-opencv)"
    if not hasattr(cv2, "FaceDetectorYN") or not hasattr(cv2, "FaceRecognizerSF"):
        return False, f"OpenCV {cv2.__version__} sem os módulos YuNet/SFace (precisa da versão 4.7+)"
    return True, f"OpenCV {cv2.__version__} · {'CUDA' if _cuda_available() else 'CPU'}"


def _cuda_available() -> bool:
    try:
        return cv2.cuda.getCudaEnabledDeviceCount() > 0
    except Exception:  # noqa: BLE001 - build sem CUDA
        return False


def ensure_models(
    models_dir: Path,
    log: Log | None = None,
    cancel: threading.Event | None = None,
    progress: Progress | None = None,
) -> tuple[Path, Path]:
    paths = []
    for spec in (DETECTOR, RECOGNIZER):
        dest = models_dir / spec.filename
        if not dest.exists() and log:
            log(f"Baixando o modelo {spec.filename} (uma vez só)…")
        paths.append(download.fetch(spec.url, dest, spec.sha256, progress=progress, cancel=cancel))
    return paths[0], paths[1]


@dataclass(slots=True)
class FaceReference:
    label: str
    embedding: object  # numpy.ndarray (128,), norma 1
    sources: list[str]
    preview: str = ""  # recorte alinhado do rosto (JPEG) para mostrar na interface

    @property
    def fingerprint(self) -> str:
        """Identifica a referência no cache (muda se as fotos mudarem)."""
        return hashlib.sha1(np.round(self.embedding, 4).tobytes()).hexdigest()[:12]


@dataclass(frozen=True, slots=True)
class FaceSegment:
    start: float
    end: float
    score: float  # maior similaridade dentro do bloco

    @property
    def duration(self) -> float:
        return self.end - self.start


class FaceEngine:
    """Detector + reconhecedor carregados uma vez (os modelos somam ~39 MB)."""

    def __init__(self, detector: Path, recognizer: Path):
        ok, detail = available()
        if not ok:
            raise FaceError(detail)
        cv2.utils.logging.setLogLevel(cv2.utils.logging.LOG_LEVEL_ERROR)
        if _cuda_available():
            backend, target = cv2.dnn.DNN_BACKEND_CUDA, cv2.dnn.DNN_TARGET_CUDA
        else:
            backend, target = cv2.dnn.DNN_BACKEND_DEFAULT, cv2.dnn.DNN_TARGET_CPU
        self._detector = cv2.FaceDetectorYN.create(
            str(detector), "", FRAME_SIZE, _MIN_DETECTION_SCORE, 0.3, 5000, backend, target
        )
        self._recognizer = cv2.FaceRecognizerSF.create(str(recognizer), "", backend, target)
        self._input_size = FRAME_SIZE
        self._lock = threading.Lock()  # os objetos do OpenCV não são reentrantes

    def _faces(self, image) -> list:
        h, w = image.shape[:2]
        if (w, h) != self._input_size:
            self._detector.setInputSize((w, h))
            self._input_size = (w, h)
        _, faces = self._detector.detect(image)
        if faces is None:
            return []
        return [f for f in faces if min(f[2], f[3]) >= _MIN_FACE_PX]

    def _embedding(self, image, face):
        feature = self._recognizer.feature(self._recognizer.alignCrop(image, face)).flatten()
        return feature / (np.linalg.norm(feature) or 1.0)

    def reference(self, images: list[Path], label: str = "", preview_dir: Path | None = None) -> FaceReference:
        """Cria a referência a partir de uma ou mais fotos da pessoa."""
        if not images:
            raise FaceError("Escolha pelo menos uma foto do rosto.")
        vectors, preview = [], ""
        with self._lock:
            for path in images:
                image = cv2.imread(str(path))
                if image is None:
                    raise FaceError(f"Não consegui abrir a imagem {Path(path).name}.")
                # Fotos grandes: reduz antes de detectar (o YuNet é treinado em rostos pequenos/médios).
                scale = min(1.0, 1280 / max(image.shape[:2]))
                if scale < 1.0:
                    image = cv2.resize(image, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
                faces = self._faces(image)
                if not faces:
                    raise FaceError(f"Nenhum rosto encontrado em {Path(path).name}. Use uma foto de frente e nítida.")
                face = max(faces, key=lambda f: f[2] * f[3])  # o maior rosto da foto
                vectors.append(self._embedding(image, face))
                if preview_dir is not None and not preview:
                    preview = str(_write_round_preview(image, face, preview_dir, path))
        mean = np.mean(vectors, axis=0)
        mean /= np.linalg.norm(mean) or 1.0
        name = label.strip() or Path(images[0]).stem
        return FaceReference(name, mean, [str(p) for p in images], preview)

    def similarity(self, frame, reference: FaceReference) -> float:
        """Maior similaridade entre os rostos do quadro e a referência (0 se nenhum)."""
        with self._lock:
            best = 0.0
            for face in self._faces(frame):
                best = max(best, float(np.dot(self._embedding(frame, face), reference.embedding)))
            return best


def _write_round_preview(image, face, folder: Path, source: Path, size: int = 160) -> Path:
    """Recorte do rosto em PNG redondo (fundo transparente) para a interface.

    O recorte com folga mostra o rosto inteiro; o círculo é feito aqui para não
    depender de efeitos gráficos do QML (indisponíveis no renderizador por software).
    """
    x, y, w, h = (int(v) for v in face[:4])
    side = int(max(w, h) * 1.6)
    cx, cy = x + w // 2, y + h // 2
    padded = cv2.copyMakeBorder(image, side, side, side, side, cv2.BORDER_REPLICATE)
    crop = padded[cy - side // 2 + side: cy + side // 2 + side, cx - side // 2 + side: cx + side // 2 + side]
    crop = cv2.resize(crop, (size, size), interpolation=cv2.INTER_AREA)
    alpha = np.zeros((size, size), np.uint8)
    cv2.circle(alpha, (size // 2, size // 2), size // 2 - 1, 255, -1, cv2.LINE_AA)
    folder.mkdir(parents=True, exist_ok=True)
    out = folder / f"rosto-{hashlib.sha1(str(source).encode()).hexdigest()[:10]}.png"
    cv2.imwrite(str(out), np.dstack([crop, alpha]))
    return out


# -- quadros --------------------------------------------------------------

def frames(
    source: str,
    fps: float = 1.0,
    start: float = 0.0,
    headers: dict[str, str] | None = None,
    cancel: threading.Event | None = None,
    size: tuple[int, int] = FRAME_SIZE,
) -> Iterator[tuple[float, object]]:
    """Gera ``(segundo, quadro BGR)`` amostrados a ``fps`` a partir de ``start``.

    O quadro é reduzido e centralizado com tarja em ``size``, então o tamanho
    é sempre conhecido e nenhum ``ffprobe`` é necessário (nem para URLs).
    """
    w, h = size
    cmd = ["ffmpeg", "-hide_banner", "-v", "error", "-nostdin"]
    if headers:
        if agent := headers.get("User-Agent"):
            cmd += ["-user_agent", agent]
        extra = "".join(f"{k}: {v}\r\n" for k, v in headers.items() if k != "User-Agent")
        if extra:
            cmd += ["-headers", extra]
    if start > 0:
        cmd += ["-ss", f"{start:.3f}"]
    cmd += [
        "-i", source, "-map", "0:v:0", "-an", "-sn",
        "-vf", (f"fps={fps},scale={w}:{h}:force_original_aspect_ratio=decrease,"
                f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2"),
        "-pix_fmt", "bgr24", "-f", "rawvideo", "pipe:1",
    ]
    frame_bytes = w * h * 3
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=frame_bytes)
    except OSError as e:
        raise FaceError(f"FFmpeg não encontrado: {e}") from e
    errors: list[bytes] = []
    reader = threading.Thread(target=lambda: errors.append(proc.stderr.read()), daemon=True)
    reader.start()
    index = 0
    try:
        while True:
            if cancel is not None and cancel.is_set():
                raise Cancelled()
            data = proc.stdout.read(frame_bytes)
            if len(data) < frame_bytes:
                break
            yield start + index / fps, np.frombuffer(data, np.uint8).reshape(h, w, 3)
            index += 1
    finally:
        _stop(proc)
        reader.join(timeout=2)
    if proc.returncode not in (0, None) and not (cancel is not None and cancel.is_set()):
        message = b"".join(errors).decode("utf-8", "replace").strip().splitlines()
        raise FaceError("FFmpeg falhou ao ler o vídeo: " + (message[-1] if message else f"código {proc.returncode}"))


def _stop(proc: subprocess.Popen) -> None:
    """Encerra o FFmpeg mesmo se ele estiver bloqueado escrevendo no pipe.

    Com SIGTERM o FFmpeg tenta terminar de escrever; se ninguém lê o pipe ele
    nunca sai. Fechar a nossa ponta faz a escrita falhar (EPIPE) na hora.
    """
    if proc.poll() is None:
        proc.terminate()
        proc.stdout.close()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
    else:
        proc.wait()


# -- blocos de tempo ------------------------------------------------------

def segments_from_samples(
    samples: list[tuple[float, float]],
    step: float,
    threshold: float = DEFAULT_THRESHOLD,
    max_gap: float | None = None,
    min_duration: float = 1.0,
) -> list[FaceSegment]:
    """Agrupa amostras ``(segundo, similaridade)`` em blocos onde a pessoa aparece.

    Cada amostra positiva representa ``±step/2`` ao redor do seu instante.
    Lacunas de até ``max_gap`` segundos (padrão: 2 amostras) não quebram o bloco;
    blocos menores que ``min_duration`` são descartados.
    """
    max_gap = 2 * step if max_gap is None else max_gap
    hits = sorted((t, s) for t, s in samples if s >= threshold)
    segments: list[FaceSegment] = []
    for t, score in hits:
        start, end = max(0.0, t - step / 2), t + step / 2
        if segments and start - segments[-1].end <= max_gap:
            last = segments[-1]
            segments[-1] = FaceSegment(last.start, end, max(last.score, score))
        else:
            segments.append(FaceSegment(start, end, score))
    return [
        FaceSegment(round(s.start, 3), round(s.end, 3), round(s.score, 3))
        for s in segments if s.duration >= min_duration
    ]


def to_json(segments: list[FaceSegment]) -> list[dict]:
    """``[{"start": "00:01:23", "end": "00:01:45", ...}]`` para relatórios e integrações."""
    return [
        {"start": format_timestamp(s.start, millis=False), "end": format_timestamp(s.end, millis=False),
         "start_seconds": s.start, "end_seconds": s.end, "similarity": s.score}
        for s in segments
    ]


# -- varredura de um vídeo ------------------------------------------------

def scan(
    engine: FaceEngine,
    reference: FaceReference,
    open_source: Callable[[], tuple[str, dict[str, str] | None]],
    fps: float = 1.0,
    threshold: float = DEFAULT_THRESHOLD,
    duration: float | None = None,
    progress: Progress | None = None,
    cancel: threading.Event | None = None,
    log: Log | None = None,
    retries: int = 3,
) -> list[FaceSegment]:
    """Procura a pessoa no vídeo inteiro e retorna os blocos onde ela aparece.

    ``open_source`` devolve ``(caminho ou URL, cabeçalhos HTTP)``. Se o stream
    cair no meio (URLs do YouTube expiram e às vezes são recusadas), a leitura
    recomeça do último segundo analisado com uma URL nova.
    """
    samples: list[tuple[float, float]] = []
    position, attempt = 0.0, 0
    while True:
        source, headers = open_source()
        try:
            for t, frame in frames(source, fps, position, headers, cancel):
                samples.append((t, engine.similarity(frame, reference)))
                position = t + 1 / fps
                if progress and duration:
                    progress(min(1.0, position / duration))
            break
        except FaceError as e:
            attempt += 1
            if attempt > retries:
                raise
            if log:
                log(f"Leitura do vídeo interrompida em {format_timestamp(position, millis=False)}; retomando… ({e})")
    if duration and position < duration - 5 * (1 / fps) and log:
        log(f"O vídeo terminou antes do esperado ({format_timestamp(position, millis=False)}).")
    return segments_from_samples(samples, 1 / fps, threshold)


def cache_file(cache_dir: Path, video_id: str, reference: FaceReference, fps: float, threshold: float) -> Path:
    return cache_dir / f"{video_id}.{reference.fingerprint}.{fps:g}fps.{threshold:g}.json"


def load_cached(path: Path) -> list[FaceSegment] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return [FaceSegment(d["start_seconds"], d["end_seconds"], d["similarity"]) for d in data]


def save_cached(path: Path, segments: list[FaceSegment]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(to_json(segments), ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(path)
