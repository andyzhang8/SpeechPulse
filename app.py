import logging
import os
import threading
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, Response, abort, jsonify, request, send_file, send_from_directory
from flask_socketio import SocketIO, join_room
from werkzeug.exceptions import NotFound

from camera import CameraWorker
from session import AnalysisError, PresentationSession, SessionStore, analyze_session
from speech import warm_up

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("app")

ROOT = Path(__file__).resolve().parent
DIST = ROOT / "reactapp" / "dist"
UPLOADS = ROOT / "uploads"
UPLOADS.mkdir(exist_ok=True)

PRESENTATION_TYPES = {
    "presentation": "Presentation",
    "interview": "Interview answer",
    "pitch": "Pitch",
    "class": "Class presentation",
}
AUDIO_TYPES = {".webm", ".ogg", ".m4a", ".mp4", ".wav"}
LIVE_INTERVAL = 0.33  # live metrics at ~3 Hz while video streams at camera rate

app = Flask(__name__, static_folder=None)
socketio = SocketIO(app)
sessions = SessionStore()
camera = CameraWorker(sessions, index=int(os.getenv("CAMERA_INDEX", "0")), model=os.getenv("POSE_MODEL", "lite"))








def _status(session: PresentationSession) -> dict:
    return {"id": session.id, "kind": session.kind, "status": session.status, "steps": session.steps, "error": session.error}


def _session_or_404(session_id: str) -> PresentationSession:
    session = sessions.get(session_id)
    if session is None:
        abort(404)
    return session


@app.errorhandler(404)
def not_found(_):
    return jsonify(error="Not found"), 404


@app.get("/video_feed")
def video_feed():
    if not camera.ensure_running():
        return jsonify(error=camera.error or "Camera unavailable."), 503
    return Response(camera.stream(), mimetype="multipart/x-mixed-replace; boundary=frame")


@app.get("/api/camera")
def camera_status():
    return jsonify(error=camera.error)


@app.post("/api/sessions")
def start_session():
    kind = PRESENTATION_TYPES.get((request.get_json(silent=True) or {}).get("kind"), "Presentation")
    # track posture even if no one's watching
    camera.ensure_running()
    session = sessions.start(kind, camera.aspect)
    socketio.start_background_task(_stream_live_metrics, session)
    log.info("Session %s started (%s)", session.id, kind)
    return jsonify(_status(session)), 201


@app.get("/api/sessions/<session_id>")
def session_status(session_id: str):
    return jsonify(_status(_session_or_404(session_id)))


@app.post("/api/sessions/<session_id>/finish")
def finish_session(session_id: str):
    session = _session_or_404(session_id)
    upload = request.files.get("audio")
    suffix = Path(upload.filename).suffix.lower() if upload and upload.filename else ""
    if upload and suffix not in AUDIO_TYPES:
        return jsonify(error=f"Unsupported audio type '{suffix}'."), 400
    if not session.finish():
        return jsonify(error="This session has already finished."), 409

    audio_path = None
    if upload:
        audio_path = UPLOADS / f"{session.id}{suffix}"
        upload.save(audio_path)
        if audio_path.stat().st_size == 0:
            audio_path.unlink()
            audio_path = None
    log.info("Session %s finished after %.1fs at %.1f camera fps", session.id, session.duration, camera.fps)
    socketio.start_background_task(_analyze, session, audio_path)
    return jsonify(_status(session)), 202


@app.delete("/api/sessions/<session_id>")
def abandon_session(session_id: str):
    _session_or_404(session_id).finish("abandoned")
    return "", 204


@app.get("/api/sessions/<session_id>/report")
def session_report(session_id: str):
    session = _session_or_404(session_id)
    if session.report is None:
        return jsonify(_status(session)), 409
    return jsonify(session.report.model_dump())


@app.get("/api/sessions/<session_id>/video")
def session_video(session_id: str):
    path = UPLOADS / f"{_session_or_404(session_id).id}.mp4"
    if not path.exists():
        abort(404)
    return send_file(path, mimetype="video/mp4", conditional=True)


@app.get("/")
@app.get("/<path:path>")
def spa(path: str = "index.html"):
    try:
        return send_from_directory(DIST, path)
    except NotFound:
        return send_from_directory(DIST, "index.html")


@socketio.on("join")
def join(data):
    session = sessions.get(str((data or {}).get("session_id", "")))
    if session is None:
        return {"error": "Unknown session"}
    join_room(session.id)
    return _status(session)


def _stream_live_metrics(session: PresentationSession) -> None:
    while session.recording:
        socketio.emit("live_metrics", {"elapsed": round(session.duration, 1), **session.posture.live}, to=session.id)
        socketio.sleep(LIVE_INTERVAL)


def _analyze(session: PresentationSession, audio_path: Path | None) -> None:
    def progress(step: str, state: str) -> None:
        session.steps[step] = state
        socketio.emit("analysis_progress", {"step": step, "status": state}, to=session.id)

    try:
        session.report = analyze_session(session, audio_path, UPLOADS, progress, camera.pose_error)
        session.status = "done"
        socketio.emit("analysis_complete", {"id": session.id}, to=session.id)
    except AnalysisError as exc:
        session.status, session.error = "failed", str(exc)
        socketio.emit("analysis_failed", {"error": session.error}, to=session.id)
    except Exception:
        # unexpected bug must still reach browser instead of hanging
        log.exception("Analysis crashed for session %s", session.id)
        session.status, session.error = "failed", "Something went wrong while analyzing this session."
        socketio.emit("analysis_failed", {"error": session.error}, to=session.id)


if __name__ == "__main__":
    threading.Thread(target=warm_up, name="pyin-warmup", daemon=True).start()
    port = int(os.getenv("PORT", "5000"))
    log.info("Running at http://127.0.0.1:%d", port)
    socketio.run(app, host="127.0.0.1", port=port, allow_unsafe_werkzeug=True)
