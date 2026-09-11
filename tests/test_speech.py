from schemas import Segment, Transcript, Word
from speech import analyze_speech, find_fillers


def words_at(start: float, end: float, wpm: int) -> list[Word]:
    count = round((end - start) * wpm / 60)
    step = (end - start) / count
    return [Word(word="word", start=start + i * step, end=start + (i + 0.8) * step) for i in range(count)]


def test_fillers_need_filler_usage_and_snap_to_word_times():
    tokens = "Um so like I like this so that you know it works".split()
    words = [Word(word=w, start=i * 0.5, end=i * 0.5 + 0.4) for i, w in enumerate(tokens)]
    text = "Um, so, like, I like this so that, you know, it works."
    transcript = Transcript(text=text, segments=[Segment(start=0, end=6, text=text)], words=words)

    fillers = find_fillers(transcript)

    assert [f.word for f in fillers] == ["um", "so", "like", "you know"]
    assert [f.time for f in fillers] == [0.0, 0.5, 1.0, 4.0]


def test_pace_spike_reports_before_and_peak():
    words = words_at(0, 20, 140) + words_at(20, 30, 195) + words_at(30, 45, 140)
    transcript = Transcript(text="", segments=[Segment(start=0, end=45, text="steady talk")], words=words)

    speech = analyze_speech(transcript, [], None)

    fast = [e for e in speech.events if e.type == "high_pace"]
    assert len(fast) == 1
    assert 18 <= fast[0].start <= 22 and 28 <= fast[0].end <= 33
    assert fast[0].metadata["peak_wpm"] >= 185
    assert 130 <= fast[0].metadata["wpm_before"] <= 150
    assert 145 <= speech.wpm <= 160


def test_silence_yields_no_speech_metrics():
    speech = analyze_speech(Transcript(text="", segments=[], words=[]), [], None)
    assert speech.wpm is None and speech.events == []
