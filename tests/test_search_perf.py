import random
import time
from difflib import SequenceMatcher

from youtube_cut.core.models import Word
from youtube_cut.core.search import find_matches, normalize


def _transcript(n_words: int, seed: int = 7) -> list[Word]:
    """Transcrição sintética com vocabulário realista (~3 mil palavras) e nomes salpicados."""
    rnd = random.Random(seed)
    letters = "abcdefghijlmnoprstuvz"
    vocab = ["".join(rnd.choice(letters) for _ in range(rnd.randint(2, 11))) for _ in range(3000)]
    vocab += ["Bárbara", "Barbra", "bárbara,", "Bárbaro", "Tales", "Thales", "Mendonça", "Ruscher", "Rucher"]
    words = [rnd.choice(vocab) for _ in range(n_words)]
    return [Word(i * 0.4, i * 0.4 + 0.35, w) for i, w in enumerate(words)]


def _brute_force(words, term, fuzzy):
    target = normalize(term)
    out = []
    for w in words:
        tok = normalize(w.text)
        if tok == target or (len(target) >= 4 and tok and
                             SequenceMatcher(None, tok, target).ratio() >= 1 - fuzzy):
            out.append(w.start)
    return out


def test_fuzzy_search_is_fast_on_long_lives():
    words = _transcript(60_000)
    started = time.perf_counter()
    matches = find_matches(words, ["Bárbara", "Tales Mendonça", "Ruscher"], fuzzy=0.2)
    elapsed = time.perf_counter() - started
    assert matches
    assert elapsed < 0.5, f"busca fuzzy levou {elapsed:.2f}s"


def test_optimized_fuzzy_matches_brute_force():
    words = _transcript(5_000, seed=3)
    for fuzzy in (0.0, 0.2, 0.35):
        fast = [m.start for m in find_matches(words, ["Bárbara"], fuzzy=fuzzy)]
        assert fast == _brute_force(words, "Bárbara", fuzzy), fuzzy
