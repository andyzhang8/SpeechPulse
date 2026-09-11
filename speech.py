"""Transcription and speech analytics"""

import re
import subprocess
from collections import Counter
from itertools import groupby, pairwise
from pathlib import Path

import imageio_ffmpeg
import librosa
import numpy as np
from openai import OpenAI

from schemas import Filler, PaceWindow, PitchWindow, PresentationEvent, Segment, SpeechAnalysis, Transcript, Word

# imageio-ffmpeg ships static binary
FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
SAMPLE_RATE = 16000

# whisper treats prompt as context not instructions
STYLE_PROMPT = "Umm, so, uh, let me think... like, you know, I mean, hmm. Okay, so here's the, uh, plan."

_HESITATIONS = r"u+m+|u+h+|e+r+m*|a+h+|h+m+|m{2,}"
_DISCOURSE = r"like|so|well|okay|right|actually|basically|literally|honestly|you know|i mean"
# hesitations always count
FILLER_PATTERN = re.compile(
    rf"\b(?:{_HESITATIONS})\b|\b(?:{_DISCOURSE})\b(?=,)|(?<=,\s)(?:{_DISCOURSE})\b(?=[.?!])",
    re.IGNORECASE,
)

PACE_WINDOW, PACE_STEP = 8.0, 2.0
FAST_WPM, SLOW_WPM = 170, 100
MIN_PAUSE = 2.0
CLUSTER_GAP, CLUSTER_MIN = 6.0, 3

PITCH_HOP = 320  # 20 ms at 16 kHz
PITCH_WINDOW = 5.0
FLAT_SEMITONES, VARIED_SEMITONES = 1.5, 3.5






def transcribe(audio_path: Path) -> Transcript:
    with open(audio_path, "rb") as audio:
        result = OpenAI().audio.transcriptions.create(
            model="whisper-1",
            file=audio,
            language="en",
            prompt=STYLE_PROMPT,
            response_format="verbose_json",
            timestamp_granularities=["word", "segment"],
        )
    return Transcript(
        text=result.text.strip(),
        segments=[Segment(start=s.start, end=s.end, text=s.text.strip()) for s in result.segments or []],
        words=[Word(word=w.word.strip(), start=w.start, end=w.end) for w in result.words or []],
    )
def decode_audio(audio_path: Path) -> np.ndarray:
    result = subprocess.run(
        [FFMPEG, "-loglevel", "error", "-i", str(audio_path), "-ac", "1", "-ar", str(SAMPLE_RATE), "-f", "f32le", "-"],
        capture_output=True,
        check=True,
    )
    return np.frombuffer(result.stdout, dtype=np.float32)



def find_fillers(transcript: Transcript) -> list[Filler]:
    fillers = []
    for seg in transcript.segments:
        seg_words = [w for w in transcript.words if seg.start - 0.5 <= w.start <= seg.end + 0.5]
        used: set[float] = set()
        for match in FILLER_PATTERN.finditer(seg.text):
            phrase = match.group(0).lower()
            estimate = seg.start + (seg.end - seg.start) * match.start() / max(len(seg.text), 1)
            head = phrase.split()[0]
            candidates = [w.start for w in seg_words if re.sub(r"[^\w']", "", w.word.lower()) == head and w.start not in used]
            time = min(candidates, key=lambda t: abs(t - estimate)) if candidates else estimate
            used.add(time)
            fillers.append(Filler(word=phrase, time=round(time, 2)))
    return sorted(fillers, key=lambda f: f.time)
def filler_events(fillers: list[Filler]) -> list[PresentationEvent]:
    events = [
        PresentationEvent(type="filler", category="speech", start=f.time, end=f.time, label=f'"{f.word}"')
        for f in fillers
    ]
    clusters: list[list[Filler]] = []
    for f in fillers:
        if clusters and f.time - clusters[-1][-1].time <= CLUSTER_GAP:
            clusters[-1].append(f)
        else:
            clusters.append([f])

    for group in clusters:
        if len(group) >= CLUSTER_MIN:
            events.append(
                PresentationEvent(
                    type="filler_cluster",
                    category="speech",
                    start=group[0].time,
                    end=group[-1].time + 0.5,
                    severity=min(1.0, len(group) / 6),
                    label=f"{len(group)} fillers",
                    metadata={"count": len(group), "words": dict(Counter(f.word for f in group))},
                )
            )
    return events
def pace_windows(transcript: Transcript) -> list[PaceWindow]:
    """WPM over sliding windows"""
    words = transcript.words
    if len(words) < 5:
        return []
    first, last = words[0].start, words[-1].end
    if last - first <= PACE_WINDOW:
        return [PaceWindow(start=first, end=last, wpm=round(len(words) / (last - first) * 60))]

    mids = np.array([(w.start + w.end) / 2 for w in words])
    windows = []
    for start in [*np.arange(first, last - PACE_WINDOW, PACE_STEP), last - PACE_WINDOW]:
        count = np.count_nonzero((mids >= start) & (mids < start + PACE_WINDOW))
        windows.append(PaceWindow(start=round(float(start), 2), end=round(float(start + PACE_WINDOW), 2), wpm=round(count / PACE_WINDOW * 60)))
    return windows



def pace_events(windows: list[PaceWindow], baseline: int) -> list[PresentationEvent]:
    def classify(w: PaceWindow) -> str | None:
        if w.wpm >= FAST_WPM or (w.wpm >= 150 and w.wpm >= baseline * 1.2):
            return "high_pace"
        if w.wpm <= SLOW_WPM:
            return "low_pace"
        return None

    events = []
    for kind, group in groupby(windows, key=classify):
        run = list(group)
        if kind is None:
            continue
        prior = [w for w in windows if w.end <= run[0].start + 1e-6]
        metadata = {"wpm_before": prior[-1].wpm if prior else None, "typical_wpm": baseline}
        if kind == "high_pace":
            peak = max(w.wpm for w in run)
            severity, label, metadata["peak_wpm"] = (peak - 150) / 50, "Fast pace", peak
        else:
            low = min(w.wpm for w in run)
            severity, label, metadata["lowest_wpm"] = (120 - low) / 40, "Slow pace", low
        events.append(
            PresentationEvent(
                type=kind, category="speech",
                # The middle of the flagged windows; their full union overstates the span.
                start=run[0].start + PACE_WINDOW / 4, end=run[-1].end - PACE_WINDOW / 4,
                severity=float(np.clip(severity, 0.2, 1.0)), label=label, metadata=metadata,
            )
        )
    return events
def pause_events(transcript: Transcript) -> list[PresentationEvent]:
    return [
        PresentationEvent(
            type="pause", category="speech", start=a.end, end=b.start,
            label=f"{b.start - a.end:.1f}s pause", metadata={"seconds": round(b.start - a.end, 1)},
        )
        for a, b in pairwise(transcript.words)
        if b.start - a.end >= MIN_PAUSE
    ]


def _spread(semitones: np.ndarray) -> float:
    """IQR scaled to std-equiv, robust to pyin octave errors."""
    q75, q25 = np.percentile(semitones, [75, 25])
    return float((q75 - q25) / 1.349)


def analyze_pitch(samples: np.ndarray) -> tuple[list[PitchWindow], float | None]:
    """summarize pyin pitch into windows of median Hz and semitone spread"""
    f0, voiced, _ = librosa.pyin(samples, fmin=65.0, fmax=450.0, sr=SAMPLE_RATE, frame_length=1024, hop_length=PITCH_HOP)
    times = librosa.times_like(f0, sr=SAMPLE_RATE, hop_length=PITCH_HOP)
    mask = voiced & ~np.isnan(f0)
    if mask.sum() < 50:
        return [], None

    hz, t = f0[mask], times[mask]
    semitones = 12 * np.log2(hz / np.median(hz))
    windows = []
    for start in np.arange(0, times[-1], PITCH_WINDOW):
        sel = (t >= start) & (t < start + PITCH_WINDOW)
        if sel.sum() >= 25:
            windows.append(
                PitchWindow(
                    start=round(float(start), 2),
                    end=round(float(min(start + PITCH_WINDOW, times[-1])), 2),
                    hz=round(float(np.median(hz[sel]))),
                    variation=round(_spread(semitones[sel]), 2),
                )
            )
    return windows, round(_spread(semitones), 2)


def warm_up() -> None:
    """compile pyin's numba kernels before first session w/ fresh install otherwise stalls ~1m."""
    analyze_pitch(np.sin(2 * np.pi * 150 * np.arange(SAMPLE_RATE) / SAMPLE_RATE).astype(np.float32))


def pitch_events(windows: list[PitchWindow]) -> list[PresentationEvent]:
    def classify(w: PitchWindow) -> str | None:
        if w.variation < FLAT_SEMITONES:
            return "monotone"
        if w.variation > VARIED_SEMITONES:
            return "vocal_variety"
        return None

    events = []
    for kind, group in groupby(windows, key=classify):
        run = list(group)
        if kind is None or (kind == "monotone" and len(run) < 2):
            continue
        spread = round(float(np.mean([w.variation for w in run])), 1)
        events.append(
            PresentationEvent(
                type=kind, category="speech", start=run[0].start, end=run[-1].end,
                severity=float(np.clip(1 - spread / FLAT_SEMITONES, 0.2, 1.0)) if kind == "monotone" else 0.0,
                label="Flat delivery" if kind == "monotone" else "Vocal variety",
                metadata={"semitone_spread": spread},
            )
        )
    return events


def analyze_speech(transcript: Transcript | None, pitch: list[PitchWindow], pitch_variation: float | None) -> SpeechAnalysis:
    events = pitch_events(pitch)
    if transcript is None or not transcript.words:
        return SpeechAnalysis(wpm=None, word_count=0, fillers=[], pace=[], pitch=pitch, pitch_variation=pitch_variation, events=events)

    words = transcript.words
    speaking_time = words[-1].end - words[0].start
    wpm = round(len(words) / speaking_time * 60) if speaking_time > 0 else None
    fillers = find_fillers(transcript)
    pace = pace_windows(transcript)
    events += filler_events(fillers) + pause_events(transcript)
    if wpm:
        events += pace_events(pace, wpm)

    return SpeechAnalysis(
        wpm=wpm,
        word_count=len(words),
        fillers=fillers,
        pace=pace,
        pitch=pitch,
        pitch_variation=pitch_variation,
        events=sorted(events, key=lambda e: e.start),
    )
