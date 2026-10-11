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
        description="Exemplo: youtube-cut scan @biglinux -t Bárbara --cut",
    )
    scan.add_argument("source", help="canal, link do YouTube Studio, vídeo, playlist, arquivo ou pasta local")
    scan.add_argument("-t", "--terms", required=True, help="termos separados por vírgula")
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
    return s


def _run_scan(args) -> int:
    from .core.pipeline import Pipeline, export_report
    from .core.search import parse_terms
    from .core.timefmt import format_short
    from .core.youtube import Cancelled

    settings = _settings_from_args(args)
    terms = parse_terms(args.terms)
    cancel = threading.Event()
    signal.signal(signal.SIGINT, lambda *_: cancel.set())
    pipe = Pipeline(settings, log=lambda m: print(f"  · {m}", file=sys.stderr), cancel=cancel)

    try:
        results = pipe.discover(args.source)
        print(f"{len(results)} vídeo(s) para analisar. Termos: {', '.join(terms)}\n")
        total_matches = 0
        for i, r in enumerate(results, 1):
            pipe.scan(r, terms)
            head = f"[{i}/{len(results)}] {r.video.title}"
            if r.status == "nosubs":
                print(f"{head}\n    sem legenda disponível")
            elif r.status == "error":
                print(f"{head}\n    erro: {r.error}")
            elif r.matches:
                total_matches += len(r.matches)
                print(f"{head}  ({len(r.matches)} menção(ões), legenda {r.subtitle})")
                for m in r.matches:
                    print(f"    {format_short(m.start):>8}  …{m.context}…")
                    print(f"              {r.video.link_at(m.start - 2)}")
            if cancel.is_set():
                raise Cancelled()

        print(f"\nTotal: {total_matches} menção(ões).")
        if args.report:
            print(f"Relatório: {export_report(results, args.report)}")

        if args.cut:
            jobs = [(r, c) for r in results for c in pipe.clips_for(r)]
            print(f"\nCortando {len(jobs)} trecho(s) em {settings.output_dir} …")
            for n, (r, clip) in enumerate(jobs, 1):
                out = pipe.output_path(r.video, clip, terms)
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


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.command == "scan":
        return _run_scan(args)
    from .gui.app import run

    return run(sys.argv[:1])
