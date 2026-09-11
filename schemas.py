"""Pydantic models for pipeline, coaching, frontend."""

from typing import Any, Literal

from pydantic import BaseModel, Field


class Word(BaseModel):
    word: str
    start: float
    end: float


class Segment(BaseModel):
    start: float
    end: float
    text: str


class Transcript(BaseModel):
    text: str
    segments: list[Segment]
    words: list[Word]


class PresentationEvent(BaseModel):
    type: str
    category: Literal["speech", "posture"]
    start: float
    end: float
    severity: float = 0.0
    label: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class Filler(BaseModel):
    word: str
    time: float


class PaceWindow(BaseModel):
    start: float
    end: float
    wpm: int


class PitchWindow(BaseModel):
    start: float
    end: float
    hz: int
    variation: float


class SpeechAnalysis(BaseModel):
    wpm: int | None
    word_count: int
    fillers: list[Filler]
    pace: list[PaceWindow]
    pitch: list[PitchWindow]
    pitch_variation: float | None
    events: list[PresentationEvent]


class PostureSummary(BaseModel):
    visible_percentage: int
    stable_percentage: int
    high_sway_percentage: int
    closed_posture_percentage: int
    fidget_percentage: int
    aligned_percentage: int
    movement: str


class Moment(BaseModel):
    id: str
    kind: Literal["combined", "speech", "posture", "steady"]
    label: str
    start: float
    end: float
    transcript: str
    speech: list[str]
    posture: list[str]
    event_types: list[str]



class CoachNote(BaseModel):
    title: str = Field(description="3-6 word headline, e.g. 'Rushed conclusion'.")
    description: str = Field(description="1-2 sentences tying speech and body evidence together.")
    moment_ids: list[str] = Field(description="Ids of the evidence moments this note is based on. Empty if general.")


class Improvement(CoachNote):
    try_next: str = Field(description="One concrete thing to do differently next time.")


class KeyMoment(BaseModel):
    moment_id: str
    verdict: Literal["strength", "needs_work"]
    title: str
    coaching: str = Field(description="1-2 sentences explaining what happened and why it matters.")


class CoachingReport(BaseModel):
    summary: str = Field(description="One sentence overall verdict.")
    main_recommendation: CoachNote
    strengths: list[CoachNote]
    improvements: list[Improvement]
    key_moments: list[KeyMoment]
    practice_plan: list[str]



class Score(BaseModel):
    overall: int
    voice: int | None
    body: int | None


class KeyMetrics(BaseModel):
    wpm: int | None
    filler_count: int | None
    fillers_per_minute: float | None
    posture_stability: int | None
    movement: str | None
    vocal_variety: str | None


class Insight(BaseModel):
    title: str
    description: str
    start: float | None
    end: float | None
    moment_ids: list[str]
    speech_evidence: list[str]
    posture_evidence: list[str]
    try_next: str | None = None


class TimelineMoment(Moment):
    verdict: Literal["strength", "needs_work"]
    title: str
    coaching: str


class Timeline(BaseModel):
    duration: float
    voice: list[PresentationEvent]
    body: list[PresentationEvent]
    pace: list[PaceWindow]
    moments: list[TimelineMoment]


class Report(BaseModel):
    session_id: str
    kind: str
    duration: float
    score: Score | None
    summary: str
    main_recommendation: Insight | None
    metrics: KeyMetrics
    strengths: list[Insight]
    improvements: list[Insight]
    practice_plan: list[str]
    timeline: Timeline
    transcript: list[Segment]
    notices: list[str]
    video_url: str | None
    ai_coached: bool
