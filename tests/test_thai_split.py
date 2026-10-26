from core.thai_split import Token, Word, build_lines, display_width, tokens_to_words

TEXT = "สวัสดีครับวันนี้อากาศดีมากเราจะไปเที่ยวทะเลกัน"


def make_tokens(text, chunk=4, dur=0.3):
    return [Token(text[i:i + chunk], i // chunk * dur, (i // chunk + 1) * dur)
            for i in range(0, len(text), chunk)]


def boundaries(words):
    out, pos = {0}, 0
    for w in words:
        pos += len(w.text)
        out.add(pos)
    return out


def test_display_width_ignores_combining_marks():
    assert display_width("ที่") == 1
    assert display_width("กา") == 2


def test_tokens_to_words_preserves_text_and_monotonic_times():
    words = tokens_to_words(make_tokens(TEXT))
    assert "".join(w.text for w in words) == TEXT
    assert all(w.start <= w.end for w in words)
    assert all(a.start <= b.start for a, b in zip(words, words[1:]))
    assert len(words) > 5


def test_tokens_to_words_keeps_space_as_word_separator():
    words = tokens_to_words([Token("สวัสดี", 0, 1), Token(" ครับ", 1, 2)])
    assert [w.text for w in words] == ["สวัสดี", "ครับ"]
    assert words[1].space_before is True


def test_build_lines_never_breaks_inside_a_word():
    words = tokens_to_words(make_tokens(TEXT))
    lines = build_lines(words, line_width=8, max_lines=2, max_pause=10, max_duration=100)
    cuts, pos = set(), 0
    for ln in lines:
        for row in ln.text.split("\n"):
            pos += len(row)
            cuts.add(pos)
    assert cuts <= boundaries(words)
    assert "".join(ln.text.replace("\n", "") for ln in lines) == TEXT


def test_build_lines_respects_width_and_max_lines():
    words = tokens_to_words(make_tokens(TEXT))
    lines = build_lines(words, line_width=8, max_lines=2, max_pause=10, max_duration=100)
    for ln in lines:
        rows = ln.text.split("\n")
        assert len(rows) <= 2
        assert all(display_width(r) <= 8 or r in {w.text for w in words} for r in rows)


def test_build_lines_splits_on_pause():
    words = [Word("หนึ่ง", 0, 0.5), Word("สอง", 0.6, 1.0), Word("สาม", 3.0, 3.5)]
    lines = build_lines(words, line_width=40, max_lines=2, max_pause=0.8)
    assert [ln.text for ln in lines] == ["หนึ่งสอง", "สาม"]
    assert (lines[0].start, lines[0].end) == (0, 1.0)


def test_build_lines_splits_on_max_duration():
    words = [Word("ก", i, i + 0.9) for i in range(10)]
    lines = build_lines(words, line_width=40, max_lines=2, max_pause=5, max_duration=6.0)
    assert len(lines) == 2


def test_build_lines_oversize_word_own_row():
    words = [Word("ก", 0, 0.1), Word("ประชาธิปไตยแบบยาวมาก", 0.1, 0.5), Word("ข", 0.5, 0.6)]
    lines = build_lines(words, line_width=5, max_lines=3, max_pause=5)
    assert lines[0].text.split("\n") == ["ก", "ประชาธิปไตยแบบยาวมาก", "ข"]


def test_build_lines_empty_input_returns_empty():
    assert build_lines([], line_width=10, max_lines=2) == []


def test_no_word_starts_with_a_combining_mark():
    """newmm can split an elongated filler ('อือื') so that a vowel mark starts the next word."""
    import unicodedata
    words = tokens_to_words([Token("อือื", 0.0, 1.0), Token("คนที่ประสบความสำเร็จ", 1.0, 3.0)])
    assert "".join(w.text for w in words) == "อือืคนที่ประสบความสำเร็จ"
    assert all(unicodedata.category(w.text[0]) != "Mn" for w in words)
    assert all(a.end <= b.start + 1e-9 for a, b in zip(words, words[1:]))


def test_a_misplaced_mark_goes_back_to_its_word_and_the_next_word_stays_whole():
    words = tokens_to_words([Token("อือื", 0.0, 1.0), Token("คนที่ประสบความสำเร็จ", 1.0, 3.0)])
    assert words[0].text.endswith("ื") and words[1].text.startswith("คน")
