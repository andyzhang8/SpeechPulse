"""Cross-modal evidence and coaching
"""

import json
import logging
import os

from openai import OpenAI, OpenAIError
from pydantic import ValidationError

from schemas import (
    CoachingReport, CoachNote, Improvement, Insight, KeyMetrics, KeyMoment, Moment, PaceWindow,
    PostureSummary, PresentationEvent, Report, Score, SpeechAnalysis, Timeline, TimelineMoment, Transcript,
)
from speech import PACE_STEP, PACE_WINDOW

log = logging.getLogger(__name__)

DEFAULT_MODEL = "gpt-4.1"

SPEECH_ISSUES = {"high_pace", "low_pace", "filler_cluster", "monotone"}
POSTURE_ISSUES = {"high_sway", "moderate_sway", "fidgeting", "crossed_arms", "head_turned", "head_down"}
MIN_OVERLAP = 1.0
MAX_MOMENTS = 8
STEADY_MIN = 8.0

# (short action for titles, concrete drill) - fallback when model unavailable
ADVICE = {
    "high_pace": ("Slow down", "Pause for a beat before each key point and deliberately slow the sentence that follows."),
    "low_pace": ("Keep your momentum", "Rehearse this section until the wording comes easily, so hesitations shrink."),
    "filler_cluster": ("Swap fillers for pauses", 'When you feel an "um" coming, close your mouth and pause instead.'),
    "monotone": ("Vary your voice", "Lift your pitch on the one or two words that matter most in each sentence."),
    "high_sway": ("Plant your feet", "Set your feet shoulder-width apart before you start and return to that stance on key points."),
    "moderate_sway": ("Steady your stance", "Keep your weight evenly on both feet while you deliver important lines."),
    "fidgeting": ("Settle your hands", "Let your hands rest between deliberate gestures instead of keeping them busy."),
    "crossed_arms": ("Keep your arms open", "Keep your hands visible and uncrossed, gesturing from the waist up."),
    "head_turned": ("Face your audience", "Square your head and shoulders to the camera when you make a key point."),
    "head_down": ("Look up from your notes", "Glance at notes during pauses, then lift your head before you speak."),
}

INSTRUCTIONS = """You are an experienced presentation coach reviewing a practice {kind}. You receive measured evidence from two analyzers that share one clock: speech (transcript, pace, fillers, pitch) and body (posture from a webcam).

Your value is connecting the two. Explain how the speaker's voice and body behaved at the same moments, and what they were saying then (the opening, a key claim, the conclusion). Prefer "combined" moments when choosing what to discuss.

Rules:
- Only use numbers and timestamps that appear in the evidence. Never estimate or invent measurements. When you mention pace, quote the WPM values given.
- Cite evidence by moment id in moment_ids. Each key_moment must use a moment id from the evidence, and each id at most once.
- Describe observable behavior and its likely effect on an audience ("may come across as rushed"). Never infer emotions, nerves, confidence, or personality.
- Body analysis comes from pose only: never mention eye contact or gaze. Natural gestures are good; only sustained or repetitive movement is a problem.
- If a modality is unavailable, do not comment on it beyond saying it was not analyzed.
- Do not manufacture problems. With few issues, give fewer improvements and focus on refinement.
- Write in plain, warm, direct second person. No emojis, no hype, no technical jargon (landmarks, semitones, segments, models, severity).

Output:
- summary: one sentence, at most 30 words.
- main_recommendation: the single highest-impact change. The title is an imperative such as "Slow down and stabilize your conclusion"; the description explains why using the evidence.
- strengths: 1-3 notes.
- improvements: 1-3 notes, most important first, combined observations first, each with a concrete try_next.
- key_moments: 2-6 moments worth replaying, in time order.
- practice_plan: exactly 3 short, concrete drills tied to this session, e.g. "Rehearse your final 20 seconds at a deliberate pace, pausing before the last line."
"""


def clock(t: float) -> str:
    return f"{int(t) // 60}:{int(t) % 60:02d}"

def describe(e: PresentationEvent) -> str:
    m = e.metadata
    seconds = f"{max(e.end - e.start, 1):.0f}s"
    match e.type:
        case "high_pace":
            before = m.get("wpm_before")
            if before and before <= m["peak_wpm"] - 15:
                return f"Pace rose from {before} to {m['peak_wpm']} WPM"
            return f"Fast pace, peaking at {m['peak_wpm']} WPM"
        case "low_pace":
            return f"Pace slowed to {m['lowest_wpm']} WPM"
        case "filler_cluster":
            words = ", ".join(f'"{w}"' + (f" ×{n}" if n > 1 else "") for w, n in m["words"].items())
            return f"{m['count']} fillers in {seconds} ({words})"
        case "monotone":
            return "Little pitch variation"
        case "vocal_variety":
            return "Expressive pitch variation"
        case "pause":
            return f"{m['seconds']}s pause"
        case _:
            return f"{e.label} for {seconds}"



def vocal_variety_label(spread: float | None) -> str | None:
    if spread is None:
        return None
    return "Flat" if spread < 1.8 else "Moderate" if spread < 3.0 else "Varied"
def _overlap(a: PresentationEvent, b: PresentationEvent) -> float:
    return min(a.end, b.end) - max(a.start, b.start)


def _excerpt(transcript: Transcript | None, start: float, end: float, limit: int = 45) -> str:
    if transcript is None:
        return ""
    words = " ".join(s.text for s in transcript.segments if s.start < end and s.end > start).split()
    return " ".join(words) if len(words) <= limit else " ".join(words[:limit]) + " …"
def _moment(kind, start, end, events, context, transcript, pace, label=None) -> Moment:
    types = {e.type for e in events}
    speech = [describe(e) for e in events if e.category == "speech"]
    posture = [describe(e) for e in events if e.category == "posture"]
    rates = [w.wpm for w in pace if w.start < end and w.end > start]
    if rates and not types & {"high_pace", "low_pace"}:
        speech.append(f"Pace around {round(sum(rates) / len(rates))} WPM")
    fillers = [e for e in context if e.type == "filler" and start <= e.start <= end]
    if fillers and "filler_cluster" not in types:
        speech.append(f"{len(fillers)} filler{'s' if len(fillers) > 1 else ''}")
    speech += [describe(e) for e in context if e.type == "pause" and start - 1 <= e.start and e.end <= end + 1]
    if label is None:
        label = events[0].label + (f" with {events[1].label.lower()}" if len(events) > 1 else "")
    return Moment(
        id="", kind=kind, label=label, start=round(start, 1), end=round(end, 1),
        transcript=_excerpt(transcript, start, end), speech=speech, posture=posture, event_types=sorted(types),
    )


def find_moments(
    events: list[PresentationEvent], transcript: Transcript | None, pace: list[PaceWindow], duration: float, posture_available: bool,
) -> list[Moment]:
    issues = [e for e in events if e.type in SPEECH_ISSUES | POSTURE_ISSUES]
    context = [e for e in events if e.type in ("filler", "pause")]

    pairs = []
    for i, a in enumerate(issues):
        for j, b in enumerate(issues):
            if a.category == "speech" and b.category == "posture":
                overlap = _overlap(a, b)
                if overlap > 0 and overlap >= min(MIN_OVERLAP, 0.5 * min(a.end - a.start, b.end - b.start)):
                    pairs.append((max(a.start, b.start), min(a.end, b.end), {i, j}))

    combined: list[list] = []
    for start, end, members in sorted(pairs, key=lambda p: p[0]):
        if combined and start <= combined[-1][1]:
            combined[-1][1] = max(combined[-1][1], end)
            combined[-1][2] |= members
        else:
            combined.append([start, end, set(members)])
    used = set().union(*(c[2] for c in combined))

    singles = [e for i, e in enumerate(issues) if i not in used and not (e.type == "moderate_sway" and e.end - e.start < 3)]
    singles.sort(key=lambda e: e.severity * min(e.end - e.start, 10), reverse=True)

    budget = MAX_MOMENTS - 2
    moments = [_moment("combined", s, e, [issues[i] for i in sorted(m)], context, transcript, pace) for s, e, m in combined][:budget]
    moments += [_moment(e.category, e.start, e.end, [e], context, transcript, pace) for e in singles][: budget - len(moments)]

    # positive moments: longest issue-free stretches + most expressive passage
    blockers = sorted(issues + [e for e in events if e.type == "out_of_frame"], key=lambda e: e.start)
    words = transcript.words if transcript else []
    span_start, span_end = (words[0].start, words[-1].end) if words else (0.0, duration)
    gaps, cursor = [], span_start
    for e in blockers:
        if e.start - cursor >= STEADY_MIN:
            gaps.append((cursor, min(e.start, span_end)))
        cursor = max(cursor, e.end)
    if span_end - cursor >= STEADY_MIN:
        gaps.append((cursor, span_end))

    for start, end in sorted(gaps, key=lambda g: g[1] - g[0], reverse=True)[:2]:
        moment = _moment("steady", start, end, [], context, transcript, pace, label="Steady stretch")
        if not any(e.type == "filler" and start <= e.start <= end for e in context):
            moment.speech.append("No fillers")
        if posture_available:
            moment.posture.append("Stable stance")
        moments.append(moment)

    variety = [e for e in events if e.type == "vocal_variety" and not any(_overlap(e, i) > 0 for i in issues)]
    if variety:
        best = max(variety, key=lambda e: e.end - e.start)
        moments.append(_moment("speech", best.start, best.end, [best], context, transcript, pace))

    moments.sort(key=lambda m: m.start)
    for n, m in enumerate(moments, 1):
        m.id = f"m{n}"
    return moments
def compute_score(speech: SpeechAnalysis | None, posture: PostureSummary | None, duration: float) -> Score | None:
    voice = body = None
    if speech and speech.wpm:
        pace = 100 - min(60, 1.5 * max(0, 120 - speech.wpm, speech.wpm - 160))
        erratic = sum(1 for w in speech.pace if not 105 <= w.wpm <= 175) / max(len(speech.pace), 1)
        per_minute = len(speech.fillers) / max(duration / 60, 0.25)
        fillers = max(40, 100 - 10 * max(0.0, per_minute - 1))
        variety = {"Flat": 60, "Moderate": 80, "Varied": 95}.get(vocal_variety_label(speech.pitch_variation), 80)
        voice = round(0.4 * (pace - 20 * erratic) + 0.35 * fillers + 0.25 * variety)
    if posture:
        moderate = 100 - posture.stable_percentage - posture.high_sway_percentage
        penalty = (
            0.5 * posture.high_sway_percentage + 0.2 * moderate + 0.5 * posture.closed_posture_percentage
            + 0.4 * posture.fidget_percentage + 0.3 * (100 - posture.aligned_percentage)
        )
        body = round(max(30, 100 - penalty))

    parts = [(v, w) for v, w in ((voice, 0.55), (body, 0.45)) if v is not None]
    if not parts:
        return None
    overall = round(sum(v * w for v, w in parts) / sum(w for _, w in parts))
    return Score(overall=overall, voice=voice, body=body)


def build_evidence(kind, duration, transcript, speech, posture, posture_events, moments, score) -> dict:
    def event_json(e: PresentationEvent) -> dict:
        return {"type": e.type, "start": round(e.start, 1), "end": round(e.end, 1), "detail": describe(e)}

    return {
        "presentation_type": kind,
        "duration_seconds": round(duration, 1),
        "score": score.model_dump() if score else None,
        "speech": None if speech is None else {
            "average_wpm": speech.wpm,
            "word_count": speech.word_count,
            "filler_count": len(speech.fillers),
            "fillers": [f.model_dump() for f in speech.fillers[:40]],
            "pace_timeline": [w.model_dump() for w in speech.pace[:: int(PACE_WINDOW / PACE_STEP)]],
            "vocal_variety": vocal_variety_label(speech.pitch_variation),
            "vocal_variety_by_window": [
                {"start": w.start, "end": w.end, "level": vocal_variety_label(w.variation)} for w in speech.pitch
            ],
            "events": [event_json(e) for e in speech.events if e.type != "filler"],
        },
        "body": None if posture is None else {
            "summary": posture.model_dump(),
            "events": [event_json(e) for e in posture_events],
        },
        "moments": [m.model_dump(exclude={"event_types"}) for m in moments],
        "transcript": [s.model_dump() for s in transcript.segments] if transcript else None,
    }


def coach(evidence: dict, kind: str, moments: list[Moment], speech, posture) -> tuple[CoachingReport, bool]:
    try:
        response = OpenAI().responses.parse(
            model=os.getenv("OPENAI_MODEL", DEFAULT_MODEL),
            instructions=INSTRUCTIONS.format(kind=kind.lower()),
            input=json.dumps(evidence),
            text_format=CoachingReport,
        )
        if response.output_parsed is not None:
            return response.output_parsed, True
        log.warning("Coaching model returned no structured output, using rule-based coaching")
    except (OpenAIError, ValidationError) as exc:
        log.warning("Coaching model unavailable, using rule-based coaching: %s", exc)
    return fallback_coaching(moments, speech, posture), False


def _signals(moment: Moment, inline: bool = False) -> str:
    text = "; ".join(moment.speech + moment.posture)
    return text[:1].lower() + text[1:] if inline else text


def _advice_types(moment: Moment) -> list[str]:
    return [t for t in moment.event_types if t in ADVICE]


def fallback_coaching(moments: list[Moment], speech: SpeechAnalysis | None, posture: PostureSummary | None) -> CoachingReport:
    positives = [m for m in moments if m.kind == "steady" or m.event_types == ["vocal_variety"]]
    issues = sorted(
        (m for m in moments if m not in positives),
        key=lambda m: (m.kind == "combined", len(m.event_types)),
        reverse=True,
    )

    strengths = [
        CoachNote(title=m.label, description=f"From {clock(m.start)} to {clock(m.end)}: {_signals(m)}.", moment_ids=[m.id])
        for m in positives
    ]
    if speech and speech.wpm and 120 <= speech.wpm <= 165:
        strengths.append(CoachNote(title="Comfortable pace", description=f"Your average pace was {speech.wpm} WPM, an easy speed to follow.", moment_ids=[]))
    if posture and posture.stable_percentage >= 80:
        strengths.append(CoachNote(title="Stable stance", description=f"Your posture was stable for {posture.stable_percentage}% of the time you were in frame.", moment_ids=[]))

    improvements = [
        Improvement(
            title=m.label,
            description=f"From {clock(m.start)} to {clock(m.end)}: {_signals(m)}.",
            moment_ids=[m.id],
            try_next=ADVICE[types[0]][1] if (types := _advice_types(m)) else "Replay this moment and rehearse it once more.",
        )
        for m in issues[:3]
    ]

    if issues:
        top = issues[0]
        types = _advice_types(top)
        actions = [ADVICE[t][0] for t in types][:2]
        main = CoachNote(
            title=" and ".join([actions[0], actions[1].lower()]) if len(actions) > 1 else actions[0] if actions else "Rehearse your weakest moment",
            description=f"At {clock(top.start)}–{clock(top.end)}: {_signals(top, inline=True)}. " + (ADVICE[types[0]][1] if types else ""),
            moment_ids=[top.id],
        )
        summary = f"Your delivery was mostly steady. The biggest opportunity is at {clock(top.start)}–{clock(top.end)}: {_signals(top, inline=True)}."
    else:
        main = CoachNote(title="Keep this delivery and add emphasis", description="No sustained pace, filler, or posture issues were detected. Next, practice slowing down and pausing on your single most important line.", moment_ids=[])
        summary = "Your delivery was steady throughout, with no sustained pace, filler, or posture issues detected."

    plan = list(dict.fromkeys(ADVICE[t][1] for m in issues for t in _advice_types(m)))[:3]
    plan += [
        "Record one more run and compare your pace in the final 20 seconds.",
        "Mark one line you want the audience to remember and pause before it.",
        "Rehearse your opening sentence until you can deliver it without notes.",
    ][: 3 - len(plan)]

    key = [KeyMoment(moment_id=n.moment_ids[0], verdict="needs_work", title=n.title, coaching=n.try_next) for n in improvements]
    key += [KeyMoment(moment_id=n.moment_ids[0], verdict="strength", title=n.title, coaching=n.description) for n in strengths if n.moment_ids]
    starts = {m.id: m.start for m in moments}
    key.sort(key=lambda k: starts[k.moment_id])

    return CoachingReport(summary=summary, main_recommendation=main, strengths=strengths[:3], improvements=improvements, key_moments=key, practice_plan=plan)


def assemble_report(
    *, session_id: str, kind: str, duration: float, transcript: Transcript | None, speech: SpeechAnalysis | None,
    posture: PostureSummary | None, posture_events: list[PresentationEvent], moments: list[Moment],
    coaching: CoachingReport, ai_coached: bool, score: Score | None, notices: list[str], video_url: str | None,
) -> Report:
    by_id = {m.id: m for m in moments}

    def insight(note: CoachNote, try_next: str | None = None) -> Insight:
        cited = [by_id[i] for i in note.moment_ids if i in by_id]
        return Insight(
            title=note.title, description=note.description,
            start=min((m.start for m in cited), default=None), end=max((m.end for m in cited), default=None),
            moment_ids=[m.id for m in cited],
            speech_evidence=list(dict.fromkeys(s for m in cited for s in m.speech))[:3],
            posture_evidence=list(dict.fromkeys(s for m in cited for s in m.posture))[:3],
            try_next=try_next,
        )

    key_moments = list({k.moment_id: k for k in coaching.key_moments if k.moment_id in by_id}.values())
    if not key_moments:
        key_moments = fallback_coaching(moments, speech, posture).key_moments
    cited = [
        KeyMoment(moment_id=i, verdict=verdict, title=note.title, coaching=note.description)
        for notes, verdict in (([coaching.main_recommendation], "needs_work"), (coaching.improvements, "needs_work"), (coaching.strengths, "strength"))
        for note in notes
        for i in note.moment_ids
        if i in by_id
    ]
    marked = {k.moment_id: k for k in cited} | {k.moment_id: k for k in key_moments}
    timeline_moments = sorted(
        (TimelineMoment(**by_id[i].model_dump(), verdict=k.verdict, title=k.title, coaching=k.coaching) for i, k in marked.items()),
        key=lambda m: m.start,
    )

    per_minute = round(len(speech.fillers) / max(duration / 60, 0.25), 1) if speech and speech.wpm else None
    return Report(
        session_id=session_id,
        kind=kind,
        duration=round(duration, 1),
        score=score,
        summary=coaching.summary,
        main_recommendation=insight(coaching.main_recommendation),
        metrics=KeyMetrics(
            wpm=speech.wpm if speech else None,
            filler_count=len(speech.fillers) if speech and speech.wpm else None,
            fillers_per_minute=per_minute,
            posture_stability=posture.stable_percentage if posture else None,
            movement=posture.movement if posture else None,
            vocal_variety=vocal_variety_label(speech.pitch_variation) if speech else None,
        ),
        strengths=[insight(n) for n in coaching.strengths[:3]],
        improvements=[insight(n, n.try_next) for n in coaching.improvements[:3]],
        practice_plan=coaching.practice_plan[:3],
        timeline=Timeline(
            duration=round(duration, 1),
            voice=speech.events if speech else [],
            body=posture_events,
            pace=speech.pace if speech else [],
            moments=timeline_moments,
        ),
        transcript=transcript.segments if transcript else [],
        notices=notices,
        video_url=video_url,
        ai_coached=ai_coached,
    )
