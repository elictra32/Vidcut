from core.highlights import Candidate, Line, find_highlights, transcript_for_ai


def mk(texts, step=5.0):
    return [Line(i * step, i * step + step - 0.5, t) for i, t in enumerate(texts)]


def test_scolding_window_is_found_and_labelled():
    texts = ["วันนี้เรียนเรื่องบัญชี"] * 12 + ["ทำไมโง่ขนาดนี้", "ไอ้ขี้เกียจ ไม่ได้เรื่อง", "โคตรน่าอาย"] + ["ต่อไปคือภาษี"] * 12
    cands = find_highlights(mk(texts), min_s=20, max_s=40)
    scold = [c for c in cands if c.category == "scold"]
    assert scold and scold[0].start <= 12 * 5 and scold[0].end >= 14 * 5
    assert scold[0].hits >= 3 and scold[0].label == "Scolding"


def test_funny_counts_laughter_patterns():
    texts = ["เล่าเรื่องปกติ"] * 6 + ["555555 ขำมาก", "ฮ่าๆๆ ตลกจริง"] + ["เล่าต่อ"] * 6
    funny = [c for c in find_highlights(mk(texts), min_s=20, max_s=40) if c.category == "funny"]
    assert funny and funny[0].hits >= 2


def test_nothing_telling_gives_only_general_candidates():
    cands = find_highlights(mk(["วันนี้เรียนเรื่องบัญชี"] * 30), min_s=20, max_s=40)
    assert {c.category for c in cands} == {"general"}


def test_candidates_stay_within_the_length_range_and_do_not_overlap_within_a_category():
    cands = find_highlights(mk(["ตื่นได้แล้ว ชีวิตคุณเลือกได้"] * 60), min_s=30, max_s=60)
    assert all(24 <= c.duration <= 60 for c in cands)
    wisdom = sorted((c for c in cands if c.category == "wisdom"), key=lambda c: c.start)
    for a, b in zip(wisdom, wisdom[1:]):
        assert min(a.end, b.end) - max(a.start, b.start) < 0.3 * min(a.duration, b.duration)


def test_loud_windows_beat_quiet_ones_with_the_same_words():
    texts = ["ไอ้โง่"] * 8 + ["วันนี้เรียนเรื่องบัญชี"] * 8 + ["ไอ้โง่"] * 8
    quiet_then_loud = [0.1] * 40 + [0.1] * 40 + [0.9] * 40
    cands = [c for c in find_highlights(mk(texts), quiet_then_loud, min_s=20, max_s=30) if c.category == "scold"]
    assert cands[0].start >= 80  # the loud one comes first


def test_custom_lexicon_replaces_the_default():
    cands = find_highlights(mk(["กล้วย กล้วย อร่อย"] * 12), min_s=20, max_s=40, lexicon={"scold": ["กล้วย"]})
    assert any(c.category == "scold" for c in cands)


def test_empty_input_and_transcript_export():
    assert find_highlights([]) == []
    t = transcript_for_ai([Line(65.0, 70.0, "สวัสดี"), Line(3700.0, 3705.0, "ลาก่อน")])
    assert "[01:05] สวัสดี" in t and "[1:01:40] ลาก่อน" in t and "MM:SS-MM:SS" in t
