from coach import assemble_report, build_evidence, coach, compute_score, fallback_coaching, find_moments
from schemas import PostureSummary, PresentationEvent, Segment, Transcript
from speech import analyze_speech
from tests.test_speech import words_at

PACE = PresentationEvent(
    type="high_pace", category="speech", start=30, end=40, severity=0.8, label="Fast pace",
    metadata={"peak_wpm": 181, "wpm_before": 145, "typical_wpm": 150},
)
SWAY = PresentationEvent(type="high_sway", category="posture", start=33, end=39, severity=0.8, label="Strong sway", metadata={"seconds": 6})
POSTURE = PostureSummary(
    visible_percentage=100, stable_percentage=88, high_sway_percentage=12, closed_posture_percentage=0,
    fidget_percentage=0, aligned_percentage=100, movement="Moderate",
)


def test_overlapping_pace_and_sway_become_one_combined_moment():
    moments = find_moments([PACE, SWAY], None, [], 60, True)

    combined = [m for m in moments if m.kind == "combined"]
    assert len(combined) == 1
    assert (combined[0].start, combined[0].end) == (33, 39)
    assert combined[0].label == "Fast pace with strong sway"
    assert "Pace rose from 145 to 181 WPM" in combined[0].speech
    assert combined[0].posture == ["Strong sway for 6s"]
    assert [m.kind for m in moments].count("steady") == 2

    coaching = fallback_coaching(moments, None, POSTURE)
    assert coaching.main_recommendation.title == "Slow down and plant your feet"
    assert coaching.main_recommendation.moment_ids == [combined[0].id]


def test_unrelated_events_stay_separate():
    later_sway = SWAY.model_copy(update={"start": 50, "end": 55})
    kinds = sorted(m.kind for m in find_moments([PACE, later_sway], None, [], 60, True))
    assert "combined" not in kinds
    assert {"speech", "posture"} <= set(kinds)


def test_report_without_api_key_uses_measured_fallback(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    words = words_at(0, 20, 140) + words_at(20, 30, 195) + words_at(30, 45, 140)
    transcript = Transcript(
        text="", words=words,
        segments=[Segment(start=0, end=20, text="Here is the problem."), Segment(start=20, end=45, text="And here is why it matters.")],
    )
    speech = analyze_speech(transcript, [], None)
    sway = SWAY.model_copy(update={"start": 21, "end": 28})
    moments = find_moments(speech.events + [sway], transcript, speech.pace, 46, True)
    score = compute_score(speech, POSTURE, 46)
    evidence = build_evidence("Pitch", 46, transcript, speech, POSTURE, [sway], moments, score)

    coaching, ai_coached = coach(evidence, "Pitch", moments, speech, POSTURE)
    report = assemble_report(
        session_id="abc", kind="Pitch", duration=46, transcript=transcript, speech=speech, posture=POSTURE,
        posture_events=[sway], moments=moments, coaching=coaching, ai_coached=ai_coached, score=score,
        notices=[], video_url=None,
    )

    assert not ai_coached
    assert report.main_recommendation.title == "Slow down and plant your feet"
    assert 20 <= report.main_recommendation.start <= 22
    assert report.timeline.moments and report.timeline.moments[0].verdict in ("strength", "needs_work")
    assert 0 < report.score.overall <= 100
    assert report.metrics.wpm == speech.wpm
