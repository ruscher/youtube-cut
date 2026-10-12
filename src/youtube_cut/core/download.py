"""Download de modelos (ONNX/ggml) com verificação de integridade.

O arquivo é baixado ao lado do destino com sufixo ``.part`` e só é renomeado
depois de conferido o SHA-256, então um download interrompido ou corrompido
nunca é usado.
"""

from __future__ import annotations

import hashlib
import threading
import urllib.request
from collections.abc import Callable
from pathlib import Path

from .youtube import Cancelled

_CHUNK = 1 << 16
_USER_AGENT = "youtube-cut (+https://github.com/biglinux)"


class DownloadError(RuntimeError):
    pass


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(_CHUNK), b""):
            digest.update(block)
    return digest.hexdigest()


def fetch(
    url: str,
    dest: Path,
    sha256: str | None = None,
    progress: Callable[[float], None] | None = None,
    cancel: threading.Event | None = None,
    timeout: float = 30.0,
) -> Path:
    """Baixa ``url`` para ``dest`` (se ainda não existir com o hash certo)."""
    if dest.exists() and (sha256 is None or sha256_of(dest) == sha256):
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    digest = hashlib.sha256()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response, part.open("wb") as out:
            total = int(response.headers.get("Content-Length") or 0)
            done = 0
            while block := response.read(_CHUNK):
                if cancel is not None and cancel.is_set():
                    raise Cancelled()
                out.write(block)
                digest.update(block)
                done += len(block)
                if progress and total:
                    progress(min(1.0, done / total))
    except Cancelled:
        part.unlink(missing_ok=True)
        raise
    except OSError as e:  # URLError, HTTPError e falhas de disco
        part.unlink(missing_ok=True)
        raise DownloadError(f"Não foi possível baixar {url}: {e}") from e

    if sha256 is not None and digest.hexdigest() != sha256:
        part.unlink(missing_ok=True)
        raise DownloadError(f"O arquivo baixado de {url} está corrompido (SHA-256 não confere).")
    part.replace(dest)
    return dest
