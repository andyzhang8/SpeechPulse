"""Posture analysis over pose landmarks w/ frames pooled into 0.2s ticks, measured relative to shoulder width. Intervals persist before they count so results don't depend on resolution, cam distance, or fps
"""

from collections import deque
from dataclasses import dataclass, field

import numpy as np

from schemas import PostureSummary, PresentationEvent

# MediaPipe pose landmark indices; left/right are the subject's own sides.
NOSE = 0
SHOULDERS, ELBOWS, WRISTS, HIPS = (11, 12), (13, 14), (15, 16), (23, 24)

TICK = 0.2
SWAY_WINDOW, HAND_WINDOW = 5.0, 4.0
RECENT = int(1.0 / TICK)  # ticks in the last second
VISIBLE = 0.5

LABELS = {
    "fidgeting": "Restless hands",
    "crossed_arms": "Arms crossed",
    "head_turned": "Head turned away",
    "head_down": "Looking down",
    "out_of_frame": "Out of frame",
}







def reversals(values: np.ndarray, threshold: float) -> int:
    count, direction, pivot = 0, 0.0, values[0]
    for v in values[1:]:
        delta = v - pivot
        if direction == 0:
            if abs(delta) >= threshold:
                direction, pivot = np.sign(delta), v
        elif delta * direction > 0:
            pivot = v
        elif abs(delta) >= threshold:
            count += 1
            direction, pivot = -direction, v
    return count

@dataclass
class _Run:
    start: float
    last: float
    severities: list[float] = field(default_factory=list)

    @property
    def span(self) -> float:
        return self.last - self.start + TICK


class IntervalTracker:
    def __init__(self, min_on: float, min_off: float):
        self.min_on, self.min_off = min_on, min_off
        self.run: _Run | None = None
        self.done: list[_Run] = []

    def update(self, t: float, active: bool, severity: float = 1.0) -> None:
        if active:
            if self.run is None:
                self.run = _Run(t, t)
            self.run.last = t
            self.run.severities.append(severity)
        elif self.run and t - self.run.last >= self.min_off:
            self.close()

    def close(self) -> None:
        if self.run and self.run.span >= self.min_on:
            self.done.append(self.run)
        self.run = None

    @property
    def confirmed(self) -> bool:
        return self.run is not None and self.run.span >= self.min_on

@dataclass
class _Tick:
    center: float
    scale: float
    shoulder_y: float
    nose: np.ndarray | None
    wrists: list[np.ndarray | None]
    elbows: list[np.ndarray | None]


class PostureTracker:
    def __init__(self, aspect: float = 0.75):
        self.aspect = aspect  # frame height / width, so x and y distances share units
        self._frames: list[np.ndarray] = []
        self._missing = 0
        self._tick_end = TICK
        self._ticks: deque[_Tick | None] = deque(maxlen=int(SWAY_WINDOW / TICK))
        self._scales: deque[float] = deque(maxlen=50)
        self._head_baseline: list[tuple[float, float]] = []
        self._trackers = {
            "sway": IntervalTracker(1.5, 1.0),
            "fidgeting": IntervalTracker(2.0, 1.0),
            "crossed_arms": IntervalTracker(1.5, 0.8),
            "head_turned": IntervalTracker(1.5, 0.8),
            "head_down": IntervalTracker(1.5, 0.8),
            "out_of_frame": IntervalTracker(2.0, 0.6),
        }
        self.tick_count = 0
        self.visible_count = 0
        self._activity_total = 0.0
        self.live: dict = {"visible": False}

    def update(self, t: float, landmarks: np.ndarray | None) -> None:
        while t >= self._tick_end:
            self._process_tick(self._tick_end)
            self._tick_end += TICK
        if landmarks is None:
            self._missing += 1
        else:
            self._frames.append(landmarks)

    def _point(self, lm: np.ndarray, i: int, min_visibility: float = VISIBLE) -> np.ndarray | None:
        if lm[i, 2] < min_visibility:
            return None
        return np.array([lm[i, 0], lm[i, 1] * self.aspect])

    def _pool(self) -> _Tick | None:
        frames, missing = self._frames, self._missing
        self._frames, self._missing = [], 0
        if len(frames) <= missing:
            return None
        lm = np.mean(frames, axis=0)
        left, right = (self._point(lm, i) for i in SHOULDERS)
        if left is None or right is None:
            return None
        self._scales.append(float(np.linalg.norm(left - right)))
        return _Tick(
            center=float((left[0] + right[0]) / 2),
            scale=max(float(np.median(self._scales)), 0.04),
            shoulder_y=float((left[1] + right[1]) / 2),
            nose=self._point(lm, NOSE),
            # crossed wrists often occluded - accept lower visibility for arms
            wrists=[self._point(lm, i, 0.3) for i in WRISTS],
            elbows=[self._point(lm, i, 0.3) for i in ELBOWS],
        )
    def _process_tick(self, t: float) -> None:
        tick = self._pool()
        self._ticks.append(tick)
        self.tick_count += 1
        self._trackers["out_of_frame"].update(t, tick is None)
        if tick is None:
            for name in ("sway", "fidgeting", "crossed_arms", "head_turned", "head_down"):
                self._trackers[name].update(t, False)
            self.live = {"visible": False}
            return

        self.visible_count += 1
        sway_level, sway_severity = self._sway(tick)
        activity, fidgeting = self._hands(tick)
        turned, down = self._head(tick)
        self._activity_total += activity

        self._trackers["sway"].update(t, sway_level > 0, sway_severity)
        self._trackers["fidgeting"].update(t, fidgeting)
        self._trackers["crossed_arms"].update(t, self._crossed_arms(tick))
        self._trackers["head_turned"].update(t, turned)
        self._trackers["head_down"].update(t, down)

        confirmed = {name: tracker.confirmed for name, tracker in self._trackers.items()}
        self.live = {
            "visible": True,
            "posture": ("Stable", "Some sway", "Swaying")[sway_level] if confirmed["sway"] else "Stable",
            "movement": "Restless" if confirmed["fidgeting"] else _movement_label(activity),
            "arms": "Crossed" if confirmed["crossed_arms"] else "Open",
            "alignment": "Turned away" if confirmed["head_turned"] else "Looking down" if confirmed["head_down"] else "Centered",
        }

    def _window(self, seconds: float) -> list[_Tick | None]:
        return list(self._ticks)[-int(seconds / TICK):]


    def _sway(self, tick: _Tick) -> tuple[int, float]:
        """Lateral sway: repeated side-to-side travel of the shoulder midpoint, in shoulder widths."""
        window = self._window(SWAY_WINDOW)
        xs = np.array([k.center for k in window if k is not None])
        if len(xs) < 0.6 * len(window) or len(xs) < 5:
            return 0, 0.0
        # window remembers last few s, only report while moving - end when sway stops, not window-length later
        if float(np.abs(np.diff(xs[-RECENT:])).sum()) / tick.scale < 0.15:
            return 0, 0.0
        amplitude = float(np.ptp(xs)) / tick.scale
        swings = reversals(xs, 0.12 * tick.scale)
        if (swings >= 2 and amplitude >= 0.3) or (swings >= 1 and amplitude >= 0.6):
            level = 2
        elif swings >= 1 and amplitude >= 0.18:
            level = 1
        else:
            level = 0
        return level, min(1.0, amplitude / 0.6)
    def _hands(self, tick: _Tick) -> tuple[float, bool]:
        """Hand activity (shoulder widths per second) and whether it looks like fidgeting"""
        window = self._window(HAND_WINDOW)
        activity, fidgeting = 0.0, False
        for side in (0, 1):
            points = [k.wrists[side] for k in window if k is not None and k.wrists[side] is not None]
            if len(points) < max(5, 0.6 * len(window)):
                continue
            path = np.array(points)
            steps = np.linalg.norm(np.diff(path, axis=0), axis=1) / tick.scale
            activity = max(activity, float(steps.sum()) / HAND_WINDOW)
            moving = float(np.mean(steps > 0.04))
            moving_now = float(np.mean(steps[-RECENT:] > 0.04))
            swings = max(reversals(path[:, 0], 0.08 * tick.scale), reversals(path[:, 1], 0.08 * tick.scale))
            extent = float(np.ptp(path, axis=0).max()) / tick.scale
            if moving >= 0.55 and moving_now >= 0.6 and swings >= 3 and extent < 0.9:
                fidgeting = True
        return activity, fidgeting

    def _crossed_arms(self, tick: _Tick) -> bool:
        wrists, elbows = tick.wrists, tick.elbows
        if any(p is None for p in (*wrists, *elbows)):
            return False
        below_shoulders = all(w[1] > tick.shoulder_y for w in wrists)
        crossed_over = all(np.sign(w[0] - tick.center) != np.sign(e[0] - tick.center) for w, e in zip(wrists, elbows, strict=True))
        tucked = all(np.linalg.norm(w - e) < 0.55 * tick.scale for w, e in zip(wrists, elbows[::-1], strict=True))
        return below_shoulders and (crossed_over or tucked)

    def _head(self, tick: _Tick) -> tuple[bool, bool]:
        if tick.nose is None:
            return False, False
        offset = (tick.nose[0] - tick.center) / tick.scale
        lift = (tick.shoulder_y - tick.nose[1]) / tick.scale
        if len(self._head_baseline) < 25:
            self._head_baseline.append((offset, lift))
            return False, False
        base_offset, base_lift = np.median(self._head_baseline, axis=0)
        return abs(offset - base_offset) > 0.3, base_lift - lift > 0.25

    def finalize(self) -> tuple[list[PresentationEvent], PostureSummary]:
        for tracker in self._trackers.values():
            tracker.close()

        events = []
        for run in self._trackers["sway"].done:
            high = float(np.mean(np.array(run.severities) >= 0.75)) >= 0.3
            events.append(
                PresentationEvent(
                    type="high_sway" if high else "moderate_sway", category="posture",
                    start=round(run.start, 2), end=round(run.last + TICK, 2),
                    severity=round(max(run.severities), 2),
                    label="Strong sway" if high else "Some sway",
                    metadata={"seconds": round(run.span, 1)},
                )
            )
        for name, label in LABELS.items():
            for run in self._trackers[name].done:
                events.append(
                    PresentationEvent(
                        type=name, category="posture", start=round(run.start, 2), end=round(run.last + TICK, 2),
                        severity=round(float(np.mean(run.severities)), 2), label=label,
                        metadata={"seconds": round(run.span, 1)},
                    )
                )
        events.sort(key=lambda e: e.start)

        visible_seconds = max(self.visible_count * TICK, TICK)

        def share(*types: str) -> int:
            covered = sum(e.end - e.start for e in events if e.type in types)
            return round(min(1.0, covered / visible_seconds) * 100)

        summary = PostureSummary(
            visible_percentage=round(self.visible_count / max(self.tick_count, 1) * 100),
            stable_percentage=100 - share("high_sway", "moderate_sway"),
            high_sway_percentage=share("high_sway"),
            closed_posture_percentage=share("crossed_arms"),
            fidget_percentage=share("fidgeting"),
            aligned_percentage=100 - share("head_turned", "head_down"),
            movement=_movement_label(self._activity_total / max(self.visible_count, 1)),
        )
        return events, summary


def _movement_label(activity: float) -> str:
    return "Low" if activity < 0.35 else "Moderate" if activity < 1.0 else "High"
