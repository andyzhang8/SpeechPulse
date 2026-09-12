import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { useNavigate } from "react-router-dom";
import { Square } from "lucide-react";
import { usePractice } from "@/context/practice";
import { api, ApiError, joinSession, socket } from "@/lib/api";
import { clock, cn } from "@/lib/utils";
import { PRESENTATION_TYPES, type LiveMetrics as Metrics } from "@/types";
import { CameraFeed } from "@/components/CameraFeed";
import { MicLevel } from "@/components/MicLevel";
import { Button } from "@/components/Button";
import { Wordmark } from "@/components/Wordmark";

const COUNTDOWN = 3;
const MIN_SECONDS = 3;
const MIME_TYPES = ["audio/webm;codecs=opus", "audio/webm", "audio/ogg;codecs=opus", "audio/mp4"];
const NEEDS_ATTENTION = new Set(["Swaying", "High", "Restless", "Crossed", "Turned away", "Looking down"]);

type Phase = "countdown" | "recording" | "finishing" | "error";

function startRecorder(stream: MediaStream, chunks: Blob[]) {
  const mimeType = MIME_TYPES.find((type) => MediaRecorder.isTypeSupported(type));
  const recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
  recorder.ondataavailable = (event) => {
    if (event.data.size > 0) chunks.push(event.data);
  };
  return new Promise<MediaRecorder>((resolve) => {
    recorder.onstart = () => resolve(recorder);
    recorder.start(1000);
  });
}

function stopRecorder(recorder: MediaRecorder, chunks: Blob[]) {
  return new Promise<Blob>((resolve) => {
    recorder.onstop = () => resolve(new Blob(chunks, { type: recorder.mimeType }));
    recorder.stop();
  });
}

export default function Practice() {
  const navigate = useNavigate();
  const { kind, mic, stream, requestMic, releaseMic } = usePractice();

  const [phase, setPhase] = useState<Phase>("countdown");
  const [count, setCount] = useState(COUNTDOWN);
  const [elapsed, setElapsed] = useState(0);
  const [metrics, setMetrics] = useState<Metrics | null>(null);
  const [error, setError] = useState<string | null>(null);

  const sessionRef = useRef<string | null>(null);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const audioRef = useRef<Blob | null>(null);
  const startedAt = useRef(0);

  useEffect(() => {
    if (mic === "idle") void requestMic();
  }, [mic, requestMic]);

  // countdown, then start. session clock starts when audio capture begins
  useEffect(() => {
    if (phase !== "countdown" || mic === "idle" || mic === "requesting") return;
    if (count > 0) {
      const timer = setTimeout(() => setCount((n) => n - 1), 1000);
      return () => clearTimeout(timer);
    }
    let cancelled = false;
    (async () => {
      try {
        if (stream) recorderRef.current = await startRecorder(stream, chunksRef.current);
        const session = await api.startSession(kind);
        if (cancelled) return;
        sessionRef.current = session.id;
        startedAt.current = performance.now();
        setPhase("recording");
      } catch (err) {
        setError(err instanceof ApiError ? err.message : "Couldn't start the session.");
        setPhase("error");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [phase, count, mic, stream, kind]);

  useEffect(() => {
    if (phase !== "recording" || !sessionRef.current) return;
    const leave = joinSession(sessionRef.current, () => undefined);
    socket.on("live_metrics", setMetrics);
    const timer = setInterval(() => setElapsed((performance.now() - startedAt.current) / 1000), 250);
    return () => {
      leave();
      socket.off("live_metrics", setMetrics);
      clearInterval(timer);
    };
  }, [phase]);

  // leaving mid-session abandons instead of leaving it recording
  useEffect(() => {
    const abandon = () => {
      if (recorderRef.current?.state === "recording") recorderRef.current.stop();
      if (sessionRef.current) void api.abandonSession(sessionRef.current).catch(() => undefined);
    };
    window.addEventListener("pagehide", abandon);
    return () => {
      window.removeEventListener("pagehide", abandon);
      abandon();
    };
  }, []);

  const finish = useCallback(async () => {
    const id = sessionRef.current;
    if (!id) return;
    setPhase("finishing");
    try {
      if (recorderRef.current?.state === "recording") audioRef.current = await stopRecorder(recorderRef.current, chunksRef.current);
      await api.finishSession(id, audioRef.current);
      sessionRef.current = null;
      releaseMic();
      navigate(`/results/${id}`);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't upload your recording.");
      setPhase("error");
    }
  }, [navigate, releaseMic]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Enter" && phase === "recording" && elapsed >= MIN_SECONDS) void finish();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [phase, elapsed, finish]);

  return (
    <div className="flex min-h-screen flex-col">
      <header className="flex items-center justify-between px-6 py-5">
        <Wordmark />
        <span className="text-sm text-muted">{PRESENTATION_TYPES.find((type) => type.id === kind)?.label}</span>
      </header>

      <main className="mx-auto flex w-full max-w-5xl flex-1 flex-col items-center gap-5 px-6 pb-8">
        <CameraFeed className="w-full max-w-[calc(66vh*4/3)]">
          {phase === "countdown" && (
            <div className="absolute inset-0 flex flex-col items-center justify-center bg-canvas/55 backdrop-blur-[2px]">
              <p className="eyebrow text-fg/70">Starting in</p>
              <p key={count} className="mt-2 animate-rise font-display text-8xl">
                {Math.max(count, 1)}
              </p>
            </div>
          )}
          {phase !== "countdown" && (
            <div className="absolute left-4 top-4 flex items-center gap-2.5 rounded-full bg-canvas/70 px-3.5 py-1.5 text-sm backdrop-blur">
              <span className="h-2 w-2 animate-pulse rounded-full bg-live" />
              <span className="font-medium">{phase === "finishing" ? "Saving" : "Recording"}</span>
              <span className="tabular text-muted">{clock(elapsed)}</span>
            </div>
          )}
        </CameraFeed>

        <div className="w-full max-w-[calc(66vh*4/3)]">
          <LiveMetrics metrics={metrics} stream={stream} />
        </div>

        {phase === "error" ? (
          <div className="flex flex-col items-center gap-4 text-center">
            <p className="text-sm text-attention">{error}</p>
            <div className="flex gap-3">
              <Button variant="secondary" onClick={() => navigate("/")}>
                Back to setup
              </Button>
              {audioRef.current && <Button onClick={() => void finish()}>Retry upload</Button>}
            </div>
          </div>
        ) : (
          <div className="flex flex-col items-center gap-3">
            <div className="flex items-center gap-2">
              <Button variant="ghost" onClick={() => navigate("/")} disabled={phase === "finishing"}>
                Restart
              </Button>
              <Button onClick={() => void finish()} disabled={phase !== "recording" || elapsed < MIN_SECONDS} className="min-w-36">
                <Square className="h-3.5 w-3.5 fill-current" /> Finish
              </Button>
            </div>
            <p className="text-xs text-faint">Press Enter to finish</p>
          </div>
        )}
      </main>
    </div>
  );
}
function LiveMetrics({ metrics, stream }: { metrics: Metrics | null; stream: MediaStream | null }) {
  const visible = metrics?.visible ?? false;
  const cells: [string, string | undefined][] = [
    ["Posture", visible ? metrics?.posture : "Step into frame"],
    ["Movement", visible ? metrics?.movement : undefined],
    ["Arms", visible ? metrics?.arms : undefined],
    ["Alignment", visible ? metrics?.alignment : undefined],
  ];

  return (
    <div className="grid w-full grid-cols-2 overflow-hidden rounded-xl border border-line bg-surface sm:grid-cols-5 sm:divide-x sm:divide-line">
      <Cell label="Voice">{stream ? <MicLevel stream={stream} showStatus /> : <span className="text-faint">No microphone</span>}</Cell>
      {cells.map(([label, value]) => (
        <Cell key={label} label={label}>
          <span className={cn("transition-colors duration-300", value && NEEDS_ATTENTION.has(value) ? "text-body" : value ? "text-fg" : "text-faint")}>
            {value ?? "—"}
          </span>
        </Cell>
      ))}
    </div>
  );
}


function Cell({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="px-5 py-3.5">
      <p className="eyebrow">{label}</p>
      <p className="mt-1 text-[15px] font-medium">{children}</p>
    </div>
  );
}
