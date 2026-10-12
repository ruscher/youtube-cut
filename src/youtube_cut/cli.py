"""Linha de comando. Sem argumentos, abre a interface gráfica."""

from __future__ import annotations

import argparse
import signal
import sys
import threading
from pathlib import Path

from . import __version__


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="youtube-cut",
        description="Encontra quando um termo é dito nos vídeos e corta esses trechos.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("gui", help="abre a interface gráfica (padrão)")

    scan = sub.add_parser(
        "scan",
        help="procura termos nas legendas e, opcionalmente, corta os trechos",
        description="Exemplos: youtube-cut scan @biglinux -t Bárbara --cut\n"
                    "          youtube-cut scan ~/Gravações --face barbara.jpg --face-label Bárbara --cut",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    scan.add_argument("source", help="canal, link do YouTube Studio, vídeo, playlist, arquivo ou pasta local")
    scan.add_argument("-t", "--terms", default="", help="termos separados por vírgula (opcional com --face)")
    scan.add_argument("--lang", help="idioma da legenda (padrão: pt)")
    scan.add_argument("--tab", choices=["streams", "videos", "shorts"], help="aba do canal (padrão: streams)")
    scan.add_argument("--limit", type=int, help="máximo de vídeos (0 = todos)")
    scan.add_argument("--fuzzy", type=float, help="tolerância a erros de transcrição, 0 a 0.4 (ex.: 0.2)")
    scan.add_argument("--before", type=float, help="segundos antes da menção")
    scan.add_argument("--after", type=float, help="segundos depois da menção")
    scan.add_argument("--cookies", metavar="NAVEGADOR", help="usa cookies do navegador (chrome, firefox…)")
    scan.add_argument("--report", type=Path, help="salva relatório .csv ou .json")
    scan.add_argument("--cut", action="store_true", help="corta/baixa os trechos encontrados")
    scan.add_argument("-o", "--out", help="pasta de saída dos cortes")
    scan.add_argument("--quality", choices=["2160", "1080", "720", "480", "best"])
    scan.add_argument("--fast", action="store_true", help="corte por stream copy (rápido, menos preciso)")
    scan.add_argument("--hwaccel", choices=["auto", "vaapi", "none"])

    ai = scan.add_argument_group("IA local")
    ai.add_argument("--whisper", action="store_true",
                    help="sem legenda, transcreve o áudio no computador (faster-whisper ou whisper.cpp)")
    ai.add_argument("--whisper-model", choices=["tiny", "base", "small", "medium"],
                    help="modelo da transcrição (padrão: small)")
    ai.add_argument("--face", action="append", type=Path, metavar="FOTO",
                    help="foto do rosto a procurar; repita para usar várias fotos da mesma pessoa")
    ai.add_argument("--face-label", metavar="NOME", help="nome mostrado nos trechos (padrão: nome da foto)")
    ai.add_argument("--face-sensitivity", choices=["strict", "normal", "loose"],
                    help="rigor da comparação: strict evita falsos positivos, loose aceita mais (padrão: normal)")
    ai.add_argument("--face-fps", type=float, help="quadros analisados por segundo de vídeo (padrão: 1)")
    ai.add_argument("--face-json", type=Path, help="salva os blocos de tempo em que o rosto aparece (.json)")
    return parser


def _settings_from_args(args):
    from .core.config import Settings

    s = Settings.load()
    mapping = {
        "lang": "language", "tab": "channel_tab", "limit": "max_videos", "fuzzy": "fuzzy",
        "before": "before", "after": "after", "cookies": "cookies_browser",
        "out": "output_dir", "quality": "quality", "hwaccel": "hwaccel",
    }
    for arg, attr in mapping.items():
        value = getattr(args, arg)
        if value is not None:
            setattr(s, attr, value)
    if args.fast:
        s.precise_cut = False
    if args.whisper:
        s.whisper_fallback = True
    if args.whisper_model:
        s.whisper_model = args.whisper_model
    if args.face:
        from .core.face_detector import THRESHOLDS

        s.face_enabled = True
        s.face_photos = "\n".join(str(p.expanduser().resolve()) for p in args.face)
        s.face_label = args.face_label or ""
        if args.face_sensitivity:
            s.face_threshold = THRESHOLDS[args.face_sensitivity]
        if args.face_fps:
            s.face_fps = args.face_fps
    else:
        s.face_enabled = False  # rosto só quando pedido nesta execução
    return s


def _run_scan(args) -> int:
    from .core.pipeline import Pipeline
    from .core.search import parse_terms

    settings = _settings_from_args(args)
    terms = parse_terms(args.terms)
    cancel = threading.Event()
    previous_handler = signal.signal(signal.SIGINT, lambda *_: cancel.set())
    pipe = Pipeline(settings, log=lambda m: print(f"  · {m}", file=sys.stderr), cancel=cancel)
    try:
        return _scan_and_cut(args, pipe, settings, terms, cancel)
    finally:
        signal.signal(signal.SIGINT, previous_handler)


def _scan_and_cut(args, pipe, settings, terms, cancel) -> int:
    from .core.pipeline import export_report
    from .core.timefmt import format_short
    from .core.youtube import Cancelled

    try:
        names = list(terms)
        if pipe.faces_requested:
            # valida as fotos antes de varrer: um erro aqui valeria para todos os vídeos
            reference = pipe.face_reference()
            print(f"Rosto de referência: {reference.label} ({len(reference.sources)} foto(s))")
            names.append(f"rosto {reference.label}")
        results = pipe.discover(args.source)
        print(f"{len(results)} vídeo(s) para analisar. Procurando: {', '.join(names)}\n")
        total_matches = 0
        for i, r in enumerate(results, 1):
            pipe.scan(r, terms)
            head = f"[{i}/{len(results)}] {r.video.title}"
            notes = []
            if r.status == "nosubs":
                notes.append("sem legenda disponível" + ("" if settings.whisper_fallback
                                                          else " (use --whisper para transcrever)"))
            elif r.status == "error":
                notes.append(f"erro: {r.error}")
            if r.matches:
                total_matches += len(r.matches)
                source = f", legenda {r.subtitle}" if r.subtitle else ""
                head += f"  ({len(r.matches)} menção(ões){source})"
            if r.matches or notes:
                print(head)
            for note in notes:
                print(f"    {note}")
            for m in r.matches:
                if m.is_face:
                    print(f"    {format_short(m.start):>8}  rosto de {m.spoken} até {format_short(m.end)}"
                          f" (similaridade {m.score:.0%})")
                else:
                    print(f"    {format_short(m.start):>8}  …{m.context}…")
                print(f"              {r.video.link_at(m.start - 2)}")
            if cancel.is_set():
                raise Cancelled()

        print(f"\nTotal: {total_matches} menção(ões).")
        if args.report:
            print(f"Relatório: {export_report(results, args.report)}")
        if args.face_json:
            print(f"Blocos do rosto: {_export_faces(results, args.face_json)}")

        if args.cut:
            jobs = [(r, c) for r in results for c in pipe.clips_for(r)]
            print(f"\nCortando {len(jobs)} trecho(s) em {settings.output_dir} …")
            for n, (r, clip) in enumerate(jobs, 1):
                out = pipe.output_path(r.video, clip, names)
                print(f"  [{n}/{len(jobs)}] {out.name}")
                try:
                    pipe.cut(r.video, clip, out)
                except (Cancelled, InterruptedError):
                    raise
                except Exception as e:
                    print(f"      falhou: {e}", file=sys.stderr)
    except (Cancelled, InterruptedError):
        print("\nCancelado.", file=sys.stderr)
        return 130
    except Exception as e:
        print(f"Erro: {e}", file=sys.stderr)
        return 1
    return 0


def _export_faces(results, path: Path) -> Path:
    """JSON com os blocos de tempo do rosto por vídeo: [{"start": "00:01:23", "end": ...}]."""
    import json

    from .core.face_detector import FaceSegment, to_json

    data = [
        {"video_id": r.video.id, "titulo": r.video.title, "url": r.video.url,
         "blocos": to_json([FaceSegment(m.start, m.end, m.score) for m in r.face_matches])}
        for r in results if r.face_matches
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.command == "scan":
        if not args.terms.strip() and not args.face:
            parser.error("informe os termos (-t) ou uma foto do rosto (--face)")
        return _run_scan(args)
    from .gui.app import run

    return run(sys.argv[:1])
