"""Busca de termos na transcrição, sem diferenciar acentos e maiúsculas.

"Bárbara", "barbara" e "BÁRBARA" são equivalentes. Com ``fuzzy`` > 0 também
aceitamos erros típicos do reconhecimento de fala ("Barbra", "Bárbra").
"""

from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
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


def _score_table(target: str, vocabulary: set[str], fuzzy: float) -> dict[str, float]:
    """Semelhança de cada palavra distinta da transcrição com ``target``.

    Calcular por palavra distinta (alguns milhares) em vez de por ocorrência
    (dezenas de milhares numa live longa) torna a busca aproximada ~10x mais
    rápida; os limites superiores baratos do SequenceMatcher descartam o resto.
    """
    if fuzzy <= 0 or len(target) < _FUZZY_MIN_LEN:
        return {target: 1.0} if target in vocabulary else {}
    threshold = 1.0 - fuzzy
    matcher = SequenceMatcher(None, "", target)
    table: dict[str, float] = {}
    for token in vocabulary:
        if token == target:
            table[token] = 1.0
            continue
        if not token or 2 * min(len(token), len(target)) / (len(token) + len(target)) < threshold:
            continue
        matcher.set_seq1(token)
        if matcher.real_quick_ratio() < threshold or matcher.quick_ratio() < threshold:
            continue
        ratio = matcher.ratio()
        if ratio >= threshold:
            table[token] = ratio
    return table


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
    vocabulary = set(tokens)
    positions: dict[str, list[int]] = defaultdict(list)
    for i, tok in enumerate(tokens):
        positions[tok].append(i)
    matches: list[Match] = []

    for term in terms:
        target = [t for t in (normalize(p) for p in term.split()) if t]
        if not target:
            continue
        n = len(target)
        tables = [_score_table(t, vocabulary, fuzzy) for t in target]
        starts = sorted(i for tok in tables[0] for i in positions[tok] if i + n <= len(tokens))
        for i in starts:
            scores = []
            for k in range(n):
                s = tables[k].get(tokens[i + k])
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
