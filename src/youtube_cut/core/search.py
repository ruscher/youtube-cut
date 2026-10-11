"""Busca de termos na transcrição, sem diferenciar acentos e maiúsculas.

"Bárbara", "barbara" e "BÁRBARA" são equivalentes. Com ``fuzzy`` > 0 também
aceitamos erros típicos do reconhecimento de fala ("Barbra", "Bárbra").
"""

from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher

from .models import Match, Word

_NON_WORD = re.compile(r"[^\w]+", re.UNICODE)
_CONTEXT_WORDS = 10
# Palavras curtas geram falsos positivos demais na busca aproximada.
_FUZZY_MIN_LEN = 4


def normalize(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    return _NON_WORD.sub("", stripped.casefold())


def parse_terms(raw: str | list[str]) -> list[str]:
    """'Bárbara, Ana Paula; Rafael' -> ['Bárbara', 'Ana Paula', 'Rafael']."""
    items = raw if isinstance(raw, list) else re.split(r"[,;\n]+", raw)
    seen, terms = set(), []
    for item in items:
        item = " ".join(item.split())
        key = item.casefold()
        if item and key not in seen:
            seen.add(key)
            terms.append(item)
    return terms


def _token_score(token: str, target: str, fuzzy: float) -> float:
    if token == target:
        return 1.0
    if fuzzy <= 0 or len(target) < _FUZZY_MIN_LEN or not token:
        return 0.0
    ratio = SequenceMatcher(None, token, target).ratio()
    return ratio if ratio >= 1.0 - fuzzy else 0.0


def find_matches(
    words: list[Word],
    terms: list[str],
    video_id: str = "",
    fuzzy: float = 0.0,
) -> list[Match]:
    """Retorna as ocorrências de cada termo (frases com várias palavras incluídas).

    ``fuzzy`` é a tolerância: 0 = só exato; 0.2 = aceita ~80% de semelhança.
    """
    tokens = [normalize(w.text) for w in words]
    matches: list[Match] = []

    for term in terms:
        target = [t for t in (normalize(p) for p in term.split()) if t]
        if not target:
            continue
        n = len(target)
        for i in range(len(tokens) - n + 1):
            scores = []
            for k in range(n):
                s = _token_score(tokens[i + k], target[k], fuzzy)
                if not s:
                    break
                scores.append(s)
            else:
                first, last = words[i], words[i + n - 1]
                matches.append(
                    Match(
                        video_id=video_id,
                        term=term,
                        start=first.start,
                        end=last.end,
                        spoken=" ".join(w.text for w in words[i : i + n]),
                        before=" ".join(w.text for w in words[max(0, i - _CONTEXT_WORDS) : i]),
                        after=" ".join(w.text for w in words[i + n : i + n + _CONTEXT_WORDS]),
                        score=round(min(scores), 3),
                    )
                )

    matches.sort(key=lambda m: m.start)
    return matches
