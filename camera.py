"""capture and pose tracking
thread owns camera + pose model; stream fans out latest JPEG so analysis runs at camera rate
"""

import logging
import sys
import threading
import time
import urllib.request
from collections import deque
from pathlib import Path

import cv2
import mediapipe as mp
import numpy as np
from mediapipe.tasks.python import BaseOptions
from mediapipe.tasks.python.vision import PoseLandmarker, PoseLandmarkerOptions, RunningMode

from posture import ELBOWS, HIPS, SHOULDERS, VISIBLE, WRISTS
from session import SessionStore

log = logging.getLogger(__name__)

MODEL_DIR = Path(__file__).resolve().parent / "models"
MODEL_URL = "https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_{0}/float16/latest/pose_landmarker_{0}.task"

FRAME_WIDTH = 640
JPEG_QUALITY = 75
IDLE_SECONDS = 5.0
START_TIMEOUT = 10.0
NEUTRAL, ATTENTION = (236, 236, 236), (72, 170, 245)  # BGR: soft white, warm amber
SKELETON = [
    (SHOULDERS[0], SHOULDERS[1]), (SHOULDERS[0], ELBOWS[0]), (ELBOWS[0], WRISTS[0]),
    (SHOULDERS[1], ELBOWS[1]), (ELBOWS[1], WRISTS[1]),
    (SHOULDERS[0], HIPS[0]), (SHOULDERS[1], HIPS[1]), (HIPS[0], HIPS[1]),
]


class PoseEstimator:
    """MediaPipe in VIDEO mode"""

    def __init__(self, variant: str = "lite"):
        path = MODEL_DIR / f"pose_landmarker_{variant}.task"
        if not path.exists():
            MODEL_DIR.mkdir(exist_ok=True)
            urllib.request.urlretrieve(MODEL_URL.format(variant), path)
        self._landmarker = PoseLandmarker.create_from_options(
            PoseLandmarkerOptions(
                base_options=BaseOptions(model_asset_path=str(path)),
                running_mode=RunningMode.VIDEO,
                num_poses=1,
            )
        )
        self._last_ms = -1

    def detect(self, frame_bgr: np.ndarray, t: float) -> np.ndarray | None:
        """Return a (33, 3) array of normalized x, y and visibility, or None if nobody is in frame."""
        ms = max(int(t * 1000), self._last_ms + 1)  # VIDEO mode rejects non-increasing timestamps
        self._last_ms = ms
        rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        result = self._landmarker.detect_for_video(mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb), ms)
        if not result.pose_landmarks:
            return None
        return np.array([(p.x, p.y, p.visibility or 0.0) for p in result.pose_landmarks[0]], dtype=np.float32)
def draw_pose(frame: np.ndarray, landmarks: np.ndarray, color: tuple[int, int, int]) -> None:
    h, w = frame.shape[:2]
    points = {i: (int(landmarks[i, 0] * w), int(landmarks[i, 1] * h)) for pair in SKELETON for i in pair if landmarks[i, 2] > VISIBLE}
    if not points:
        return
    overlay = frame.copy()
    for a, b in SKELETON:
        if a in points and b in points:
            cv2.line(overlay, points[a], points[b], color, 2, cv2.LINE_AA)
    for p in points.values():
        cv2.circle(overlay, p, 4, color, -1, cv2.LINE_AA)
    cv2.addWeighted(overlay, 0.6, frame, 0.4, 0, dst=frame)



class CameraWorker:
    def __init__(self, sessions: SessionStore, index: int = 0, model: str = "lite"):
        self._sessions = sessions
        self._index = index
        self._model = model
        self._estimator: PoseEstimator | None = None
        self._cond = threading.Condition()
        self._ready = threading.Event()
        self._active = False
        self._jpeg: bytes | None = None
        self._seq = 0
        self._viewers = 0
        self._last_viewed = 0.0
        self.error: str | None = None
        self.pose_error: str | None = None
        self.aspect = 0.75
        self.fps = 0.0

    def ensure_running(self) -> bool:
        """Start capturing if needed, wait until the first frame arrives or opening fails"""
        with self._cond:
            if not self._active:
                self._active = True
                self._jpeg = None
                self.error = None
                self._last_viewed = time.monotonic()
                self._ready.clear()
                threading.Thread(target=self._run, name="camera", daemon=True).start()
        self._ready.wait(START_TIMEOUT)
        return self._jpeg is not None

    def stream(self):
        """multipart MJPEG generator for each connected viewer."""
        with self._cond:
            self._viewers += 1
        try:
            seq = -1
            while True:
                with self._cond:
                    self._cond.wait_for(lambda last=seq: self._seq != last or not self._active, timeout=1.0)
                    if not self._active:
                        return
                    if self._seq == seq:
                        continue
                    seq, jpeg = self._seq, self._jpeg
                yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + jpeg + b"\r\n"
        finally:
            with self._cond:
                self._viewers -= 1
                self._last_viewed = time.monotonic()
    def _wanted(self) -> bool:
        with self._cond:
            watched = self._viewers > 0 or time.monotonic() - self._last_viewed < IDLE_SECONDS
        return watched or self._sessions.recording() is not None


    def _run(self) -> None:
        cap = cv2.VideoCapture(self._index, cv2.CAP_DSHOW if sys.platform == "win32" else cv2.CAP_ANY)
        try:
            if not cap.isOpened():
                self.error = "Camera unavailable. Close other apps that may be using it and check camera permissions."
                return
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, FRAME_WIDTH)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
            if self._estimator is None and self.pose_error is None:
                try:
                    self._estimator = PoseEstimator(self._model)
                except (OSError, RuntimeError) as exc:
                    # keep streaming video, report will say body tracking unavailable
                    self.pose_error = f"Body tracking could not start ({exc})."
                    log.exception("Pose model failed to load")
            self._capture(cap)
        finally:
            cap.release()
            with self._cond:
                self._active = False
                self._cond.notify_all()
            self._ready.set()
    def _capture(self, cap: cv2.VideoCapture) -> None:
        stamps: deque[float] = deque(maxlen=30)
        while self._wanted():
            ok, frame = cap.read()
            captured = time.monotonic()
            if not ok:
                self.error = "The camera stopped sending frames."
                return
            if frame.shape[1] != FRAME_WIDTH:
                frame = cv2.resize(frame, (FRAME_WIDTH, round(frame.shape[0] * FRAME_WIDTH / frame.shape[1])))
            self.aspect = frame.shape[0] / frame.shape[1]

            landmarks = self._estimator.detect(frame, captured) if self._estimator else None
            session = self._sessions.recording()
            if landmarks is not None:
                live = session.posture.live if session else {}
                alert = live.get("posture") == "Swaying" or live.get("arms") == "Crossed"
                draw_pose(frame, landmarks, ATTENTION if alert else NEUTRAL)

            # flip after analysis so pose keeps anatomical left/right
            jpeg = cv2.imencode(".jpg", cv2.flip(frame, 1), [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])[1].tobytes()
            if session is not None:
                session.add_frame(captured, jpeg, landmarks)
            with self._cond:
                self._jpeg = jpeg
                self._seq += 1
                self._cond.notify_all()
            self._ready.set()

            stamps.append(captured)
            if len(stamps) > 1:
                self.fps = (len(stamps) - 1) / (stamps[-1] - stamps[0])
