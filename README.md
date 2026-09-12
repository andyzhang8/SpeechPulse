# SpeechPulse

SpeechPulse is a multimodal AI presentation coach that analyzes your speech and body language together to give specific feedback on how you present.

It uses audio and webcam input to track speaking pace, filler words, pauses, pitch, swaying, fidgeting, crossed arms, and head position. Instead of analyzing these separately, SpeechPulse aligns everything on one timeline and uses an AI coaching agent to find moments where multiple signals changed together.

For example, it can identify that you sped up while starting to sway during the conclusion of your presentation, then explain what happened and what you should work on.

## How it works

SpeechPulse combines multiple AI and ML models into one analysis pipeline.

**Speech:** Whisper transcribes the presentation with timestamps. SpeechPulse then measures pace, filler words, pauses, and pitch changes throughout the recording.

**Vision:** MediaPipe PoseLandmarker processes webcam frames in real time and tracks body movement, swaying, fidgeting, crossed arms, and head alignment.

**Multimodal analysis:** Speech and posture events share the same session timeline, so the system can find moments where different signals overlap.

**AI coaching:** The coaching agent takes these measured moments as evidence and generates the final feedback, including key moments, the biggest areas to improve, and a practice plan.

The LLM is grounded in the actual measurements instead of generating scores or observations itself. Timestamps, metrics, and detected behaviors come directly from the speech and vision pipeline.

## Requirements

* Python 3.11–3.13
* Node.js 18+
* Webcam and microphone
* OpenAI API key

## Setup

From the `SpeechPulse` folder:

### Windows

```powershell id="gpmg85"
py -3.13 -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt

Copy-Item .env.example .env
# Add your OPENAI_API_KEY to .env

cd reactapp
npm install
npm run build
cd ..
```

### macOS / Linux

```bash id="7y6p3v"
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt

cp .env.example .env
# Add your OPENAI_API_KEY to .env

cd reactapp
npm install
npm run build
cd ..
```

The MediaPipe pose model downloads into `models/` the first time you run the app.

## Run

### Windows

```powershell id="jfccok"
.venv\Scripts\python app.py
```

### macOS / Linux

```bash id="mjprbx"
.venv/bin/python app.py
```

Then open:

`http://127.0.0.1:5000`

## Frontend development

Keep `app.py` running, then open another terminal:

```bash id="tkj8lu"
cd reactapp
npm run dev
```

Open `http://localhost:8080`.

Vite proxies the API, video stream, and Socket.IO requests to Flask.

## Project structure

```text id="9jg8m0"
app.py          Flask routes, Socket.IO, and analysis tasks
camera.py       Webcam capture and MediaPipe pose inference
posture.py      Body language and movement analysis
speech.py       Whisper, pace, fillers, pauses, and pitch analysis
coach.py        Multimodal event matching and AI coaching
session.py      Session state and shared audio/video timeline
schemas.py      Shared Pydantic models

reactapp/src/
  pages/        Setup, Practice, and Results
  components/   Camera, microphone, UI, and report components

tests/          pytest tests
```

## Limitations

* Only one presenter is supported at a time.
* Sessions are stored in memory and disappear when the server restarts.
* Hand-related checks only work when your hands are visible.
* Scores and thresholds are coaching heuristics, not scientifically validated behavioral measurements.
