import pytest

from youtube_cut.core.clips import build_clips
from youtube_cut.core.models import Match
from youtube_cut.core.search import find_matches, normalize, parse_terms
from youtube_cut.core.subtitles import parse_subtitle_text
from youtube_cut.core.timefmt import format_timestamp, parse_timestamp
from youtube_cut.core.youtube import _choose_track, resolve_source

# Formato real das legendas automáticas do YouTube: cada cue repete a linha
# anterior e a linha nova traz o tempo de cada palavra.
YOUTUBE_VTT = """WEBVTT
Kind: captions
Language: pt

00:00:01.000 --> 00:00:03.000 align:start position:0%

oi<00:00:01.400><c> gente,</c><00:00:01.900><c> hoje</c><00:00:02.300><c> a</c>

00:00:03.000 --> 00:00:03.010 align:start position:0%
oi gente, hoje a


00:00:03.010 --> 00:00:06.000 align:start position:0%
oi gente, hoje a
Bárbara<00:00:03.700><c> vai</c><00:00:04.000><c> falar</c><00:00:04.400><c> do</c><00:00:04.800><c> BigLinux</c>

00:00:06.000 --> 00:00:06.010 align:start position:0%
Bárbara vai falar do BigLinux


00:00:06.010 --> 00:00:08.000 align:start position:0%
Bárbara vai falar do BigLinux
&gt;&gt; obrigada!
"""

SRT = """1
00:00:10,000 --> 00:00:12,000
Olá, eu sou a <i>Barbara</i>.

2
00:00:12,000 --> 00:00:14,000
Olá, eu sou a <i>Barbara</i>.

3
00:01:00,500 --> 00:01:02,500
Ana Paula chegou
"""


def test_timestamps_roundtrip():
    assert parse_timestamp("01:02:03.456") == pytest.approx(3723.456)
    assert parse_timestamp("02:03,5") == pytest.approx(123.5)
    assert parse_timestamp("90") == 90
    assert format_timestamp(3723.456) == "01:02:03.456"


def test_youtube_vtt_uses_word_timing_and_skips_repeats():
    words = parse_subtitle_text(YOUTUBE_VTT)
    texts = [w.text for w in words]
    assert texts == ["oi", "gente,", "hoje", "a", "Bárbara", "vai", "falar", "do",
                     "BigLinux", ">>", "obrigada!"]
    barbara = words[4]
    assert barbara.start == pytest.approx(3.010)
    assert barbara.end == pytest.approx(3.700)


def test_srt_dedups_and_spreads_words():
    words = parse_subtitle_text(SRT)
    assert [w.text for w in words][:5] == ["Olá,", "eu", "sou", "a", "Barbara."]
    assert words[0].start == 10.0
    assert 10.0 < words[4].start < 12.0
    assert words[-1].end == pytest.approx(62.5)


def test_search_ignores_accents_case_and_punctuation():
    words = parse_subtitle_text(SRT)
    matches = find_matches(words, ["BÁRBARA"], "vid")
    assert len(matches) == 1
    assert matches[0].spoken == "Barbara."
    assert normalize("Bárbara,") == "barbara"


def test_search_multiword_phrase():
    words = parse_subtitle_text(SRT)
    (m,) = find_matches(words, ["ana paula"], "vid")
    assert m.spoken == "Ana Paula"
    assert m.start == pytest.approx(60.5)


def test_fuzzy_search_catches_asr_errors():
    words = parse_subtitle_text("WEBVTT\n\n00:00:01.000 --> 00:00:02.000\na Barbra chegou\n")
    assert find_matches(words, ["Bárbara"]) == []
    (m,) = find_matches(words, ["Bárbara"], fuzzy=0.2)
    assert m.spoken == "Barbra" and m.score < 1


def test_fuzzy_ignores_short_terms():
    words = parse_subtitle_text("WEBVTT\n\n00:00:01.000 --> 00:00:02.000\nana ama\n")
    assert len(find_matches(words, ["ana"], fuzzy=0.4)) == 1


def test_parse_terms():
    assert parse_terms("Bárbara, ana  paula; bárbara\nRafael") == ["Bárbara", "ana paula", "Rafael"]


def _m(start, end, vid="v"):
    return Match(vid, "x", start, end, "x")


def test_clips_padding_merge_and_bounds():
    clips = build_clips([_m(1, 2), _m(6, 7), _m(30, 31), _m(5, 5.5, "w")], before=3, after=3,
                        duration=32, merge_gap=1)
    assert [(c.video_id, c.start, c.end, len(c.matches)) for c in clips] == [
        ("v", 0.0, 10.0, 2),
        ("v", 27.0, 32.0, 1),
        ("w", 2.0, 8.5, 1),
    ]


@pytest.mark.parametrize(
    ("text", "kind", "url"),
    [
        ("https://studio.youtube.com/channel/UCJZUvE04sPBhwVVuk5g9bUg/videos/live?filter=%5B%5D",
         "channel", "https://www.youtube.com/channel/UCJZUvE04sPBhwVVuk5g9bUg/streams"),
        ("https://studio.youtube.com/channel/UCJZUvE04sPBhwVVuk5g9bUg/videos/upload",
         "channel", "https://www.youtube.com/channel/UCJZUvE04sPBhwVVuk5g9bUg/videos"),
        ("UCJZUvE04sPBhwVVuk5g9bUg", "channel",
         "https://www.youtube.com/channel/UCJZUvE04sPBhwVVuk5g9bUg/streams"),
        ("@biglinux", "channel", "https://www.youtube.com/@biglinux/streams"),
        ("youtube.com/@biglinux/videos", "channel", "https://www.youtube.com/@biglinux/videos"),
        ("https://youtu.be/fwFf-HzDrm4?t=10", "video", "https://www.youtube.com/watch?v=fwFf-HzDrm4"),
        ("https://www.youtube.com/live/fwFf-HzDrm4", "video", "https://www.youtube.com/watch?v=fwFf-HzDrm4"),
        ("https://studio.youtube.com/video/fwFf-HzDrm4/edit", "video",
         "https://www.youtube.com/watch?v=fwFf-HzDrm4"),
        ("https://www.youtube.com/playlist?list=PL123abc", "playlist",
         "https://www.youtube.com/playlist?list=PL123abc"),
    ],
)
def test_resolve_source(text, kind, url):
    src = resolve_source(text)
    assert (src.kind, src.url) == (kind, url)


def test_choose_track_prefers_manual_then_original_asr():
    vtt = lambda u: [{"ext": "json3", "url": "x"}, {"ext": "vtt", "url": u}]  # noqa: E731
    assert _choose_track({"pt-BR": vtt("m")}, {"pt-orig": vtt("a")}, "pt") == ("pt-BR", False, "m")
    assert _choose_track({}, {"pt": vtt("t"), "pt-orig": vtt("a")}, "pt") == ("pt-orig", True, "a")
    assert _choose_track({}, {"pt": vtt("t"), "en-orig": vtt("e")}, "pt") == ("en-orig", True, "e")
    assert _choose_track({}, {}, "pt") is None
