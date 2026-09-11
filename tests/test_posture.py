import numpy as np

from posture import TICK, IntervalTracker, PostureTracker

FPS = 25


def standing(dx: float = 0.0) -> np.ndarray:
    lm = np.zeros((33, 3), dtype=np.float32)
    lm[:, 2] = 0.99
    points = {
        0: (0.5, 0.30), 11: (0.6, 0.45), 12: (0.4, 0.45), 13: (0.63, 0.60), 14: (0.37, 0.60),
        15: (0.64, 0.72), 16: (0.36, 0.72), 23: (0.57, 0.80), 24: (0.43, 0.80),
    }
    for i, (x, y) in points.items():
        lm[i, :2] = (x + dx, y)
    return lm


def run(duration, pose_at, seed=7):
    rng = np.random.default_rng(seed)
    tracker = PostureTracker(aspect=0.75)
    lives = []
    for k in range(int(duration * FPS)):
        t = k / FPS
        lm = pose_at(t)
        if lm is not None:
            lm = lm.copy()
            lm[:, :2] += rng.normal(0, 0.002, (33, 2))  # landmark jitter
        tracker.update(t, lm)
        lives.append((t, dict(tracker.live)))
    events, summary = tracker.finalize()
    return events, summary, lives


def of_type(events, *types):
    return [e for e in events if e.type in types]


def test_still_speaker_has_no_events():
    events, summary, lives = run(20, lambda t: standing())
    assert events == []
    assert summary.stable_percentage == 100
    assert summary.visible_percentage == 100
    assert summary.movement == "Low"
    assert lives[-1][1] == {"visible": True, "posture": "Stable", "movement": "Low", "arms": "Open", "alignment": "Centered"}


def test_sway_becomes_one_interval_that_ends_with_the_sway():
    events, summary, lives = run(22, lambda t: standing(0.06 * np.sin(2 * np.pi * t / 2)) if 5 <= t < 15 else standing())
    sway = of_type(events, "high_sway")
    assert len(sway) == 1
    assert 5 <= sway[0].start <= 8
    assert 14.5 <= sway[0].end <= 16.5
    assert summary.high_sway_percentage >= 30
    assert any(live.get("posture") == "Swaying" for t, live in lives if 9 < t < 15)
    assert lives[-1][1]["posture"] == "Stable"


def test_crossed_arms_must_persist():
    def pose(t):
        lm = standing()
        if 5 <= t < 12 or 15 <= t < 15.4:  # one sustained crossing, one brief blip
            lm[15, :2] = (0.42, 0.58)
            lm[16, :2] = (0.58, 0.58)
        return lm

    events, summary, _ = run(20, pose)
    crossed = of_type(events, "crossed_arms")
    assert len(crossed) == 1
    assert 4.8 <= crossed[0].start <= 5.4 and 11.8 <= crossed[0].end <= 12.6
    assert 30 <= summary.closed_posture_percentage <= 40


def test_repetitive_hand_motion_is_fidgeting():
    def pose(t):
        lm = standing()
        if 5 <= t < 13:
            wiggle = 0.03 * np.sin(2 * np.pi * 1.5 * t)
            lm[15, :2] = (0.53 + wiggle, 0.68)
            lm[16, :2] = (0.47 - wiggle, 0.68 + wiggle)
        return lm

    events, _, _ = run(18, pose)
    fidget = of_type(events, "fidgeting")
    assert len(fidget) == 1
    assert 5 <= fidget[0].start <= 9 and 12.5 <= fidget[0].end <= 14.5


def test_single_expressive_gesture_is_not_fidgeting():
    def pose(t):
        lm = standing()
        if 6 <= t < 8.5:
            lm[16, :2] = (0.2, 0.4)
        return lm

    events, _, _ = run(15, pose)
    assert of_type(events, "fidgeting") == []


def test_out_of_frame_and_head_turn():
    def pose(t):
        if 12 <= t < 16:
            return None
        lm = standing()
        if 6 <= t < 10:
            lm[0, 0] += 0.08
        return lm

    events, summary, lives = run(20, pose)
    assert len(of_type(events, "out_of_frame")) == 1
    turned = of_type(events, "head_turned")
    assert len(turned) == 1 and 5.9 <= turned[0].start <= 6.4 and 9.8 <= turned[0].end <= 10.4
    assert 78 <= summary.visible_percentage <= 82
    assert any(live == {"visible": False} for t, live in lives if 13 < t < 16)


def test_interval_tracker_ignores_blips():
    tracker = IntervalTracker(min_on=1.0, min_off=0.5)
    for k in range(50):
        tracker.update(k * TICK, k in (5, 20, 21, 22, 23, 24, 25, 26))
    tracker.close()
    assert [(round(r.start, 1), round(r.last, 1)) for r in tracker.done] == [(4.0, 5.2)]
