"""Session management: shared clock, recording state, analysis pipeline.
"""

import logging
import subprocess
import threading
import time
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

import librosa
import numpy as np
from openai import OpenAIError

from coach import assemble_report, build_evidence, coach, compute_score, find_moments
from posture import TICK, PostureTracker
from schemas import PostureSummary, PresentationEvent, Report
from speech import FFMPEG, analyze_pitch, analyze_speech, decode_audio, transcribe

log = logging.getLogger(__name__)

VIDEO_FPS = 20
MAX_VIDEO_SECONDS = 300
STEPS = ("speech", "body", "connect", "report")
MIN_VISIBLE_SECONDS = 5.0
MIN_VISIBLE_PERCENT = 25
SHORT_SESSION = 15.0





class AnalysisError(Exception):
    """Neither speech nor body data was usable. The message is shown to the user."""

@dataclass
class PresentationSession:
    kind: str
    aspect: float
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    started: float = field(default_factory=time.monotonic)
    ended: float | None = None
    status: str = "recording"  # recording -> processing -> done | failed | abandoned
    steps: dict[str, str] = field(default_factory=lambda: dict.fromkeys(STEPS, "pending"))
    report: Report | None = None
    error: str | None = None
    frames: list[tuple[float, bytes]] = field(default_factory=list)
    posture: PostureTracker = field(init=False)
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def __post_init__(self):
        self.posture = PostureTracker(self.aspect)

    @property
    def duration(self) -> float:
        return (self.ended or time.monotonic()) - self.started
    @property
    def recording(self) -> bool:
        return self.ended is None

    def add_frame(self, captured_at: float, jpeg: bytes, landmarks: np.ndarray | None) -> None:
        with self.lock:
            t = captured_at - self.started
            if self.ended is not None or t < 0:
                return
            self.posture.update(t, landmarks)
            # keep frames at export rate so memory bounded for replay video
            if t <= MAX_VIDEO_SECONDS and (not self.frames or t - self.frames[-1][0] >= 0.9 / VIDEO_FPS):
                self.frames.append((t, jpeg))
    def finish(self, status: str = "processing") -> bool:
        with self.lock:
            if self.ended is not None:
                return False
            self.ended = time.monotonic()
            self.status = status
            if status == "abandoned":
                self.frames = []
            return True


class SessionStore:

    def __init__(self):
        self._sessions: dict[str, PresentationSession] = {}
        self._lock = threading.Lock()
        self.active: PresentationSession | None = None

    def start(self, kind: str, aspect: float) -> PresentationSession:
        with self._lock:
            # one camera = one live session; new start supersedes unfinished one
            if self.active is not None:
                self.active.finish("abandoned")
            session = PresentationSession(kind=kind, aspect=aspect)
            self._sessions[session.id] = session
            self.active = session
            return session
    def get(self, session_id: str) -> PresentationSession | None:
        return self._sessions.get(session_id)
    def recording(self) -> PresentationSession | None:
        session = self.active
        return session if session is not None and session.recording else None


def export_video(frames: list[tuple[float, bytes]], audio_path: Path | None, dst: Path) -> None:
    """Mux JPEG frames + audio into H.264 MP4.

    Frames come at variable rate, so constant-rate grid reuses most recent frame.
    Keeps video time = session time for timeline seeking.
    """
    picked, i = [], 0
    for k in range(int(frames[-1][0] * VIDEO_FPS) + 1):
        while i + 1 < len(frames) and frames[i + 1][0] <= k / VIDEO_FPS:
            i += 1
        picked.append(frames[i][1])

    audio = ["-i", str(audio_path), "-map", "0:v", "-map", "1:a", "-c:a", "aac", "-b:a", "96k"] if audio_path else []
    subprocess.run(
        [
            FFMPEG, "-loglevel", "error", "-y",
            "-f", "image2pipe", "-framerate", str(VIDEO_FPS), "-c:v", "mjpeg", "-i", "-",
            *audio,
            "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p", "-movflags", "+faststart",
            str(dst),
        ],
        input=b"".join(picked),
        capture_output=True,
        check=True,
    )


def _posture(session: PresentationSession, pose_error: str | None, notices: list[str]) -> tuple[list[PresentationEvent], PostureSummary | None]:
    events, summary = session.posture.finalize()
    if pose_error:
        notices.append("Body analysis was unavailable because body tracking failed to start.")
    elif session.posture.tick_count == 0:
        notices.append("Body analysis was unavailable because the camera wasn't running.")
    elif session.posture.visible_count * TICK < MIN_VISIBLE_SECONDS or summary.visible_percentage < MIN_VISIBLE_PERCENT:
        notices.append("Body analysis was unavailable because you weren't clearly in frame. Keep your head and shoulders visible.")
    else:
        if summary.visible_percentage < 70:
            notices.append(f"You were in frame for {summary.visible_percentage}% of the session, so body feedback covers only part of it.")
        return events, summary
    return [], None


def analyze_session(
    session: PresentationSession,
    audio_path: Path | None,
    out_dir: Path,
    progress: Callable[[str, str], None],
    pose_error: str | None = None,
) -> Report:
    notices: list[str] = []
    duration = session.duration
    frames, session.frames = session.frames, []

    progress("speech", "active")
    progress("body", "active")
    with ThreadPoolExecutor(max_workers=3) as pool:
        transcript_job = pitch_job = video_job = None
        if audio_path:
            transcript_job = pool.submit(transcribe, audio_path)
            pitch_job = pool.submit(lambda: analyze_pitch(decode_audio(audio_path)))
        if frames:
            video_job = pool.submit(export_video, frames, audio_path, out_dir / f"{session.id}.mp4")

        posture_events, posture = _posture(session, pose_error, notices)
        progress("body", "done")

        transcript = speech = None
        if audio_path is None:
            notices.append("Speech analysis was skipped because no microphone audio was recorded.")
        else:
            try:
                transcript = transcript_job.result()
                if not transcript.words:
                    notices.append("No speech was detected in the recording. Check that the right microphone is selected.")
            except OpenAIError as exc:
                log.warning("Transcription failed: %s", exc)
                notices.append("Transcription failed, so pace and filler feedback are unavailable.")
            try:
                pitch, spread = pitch_job.result()
            except (subprocess.CalledProcessError, librosa.ParameterError) as exc:
                log.warning("Pitch analysis failed: %s", exc)
                notices.append("Your audio couldn't be read, so vocal variety is unavailable.")
                pitch, spread = [], None
            speech = analyze_speech(transcript, pitch, spread)
            if speech.wpm is None and not speech.pitch:
                speech = None
        progress("speech", "done")

        if speech is None and posture is None:
            raise AnalysisError(" ".join(notices) or "Nothing in this session could be analyzed.")
        if duration < SHORT_SESSION:
            notices.append("This run was short, so the coaching is based on limited evidence.")

        progress("connect", "active")
        events = (speech.events if speech else []) + posture_events
        moments = find_moments(events, transcript, speech.pace if speech else [], duration, posture is not None)
        score = compute_score(speech, posture, duration)
        evidence = build_evidence(session.kind, duration, transcript, speech, posture, posture_events, moments, score)
        progress("connect", "done")

        progress("report", "active")
        coaching, ai_coached = coach(evidence, session.kind, moments, speech, posture)
        if not ai_coached:
            notices.append("AI coaching was unavailable, so this report uses rule-based feedback from your measurements.")

        video_url = None
        if video_job is not None:
            try:
                video_job.result()
                video_url = f"/api/sessions/{session.id}/video"
            except subprocess.CalledProcessError as exc:
                log.warning("Replay video export failed: %s", exc.stderr.decode(errors="replace"))

    report = assemble_report(
        session_id=session.id, kind=session.kind, duration=duration, transcript=transcript, speech=speech,
        posture=posture, posture_events=posture_events, moments=moments, coaching=coaching, ai_coached=ai_coached,
        score=score, notices=notices, video_url=video_url,
    )
    progress("report", "done")
    return report
