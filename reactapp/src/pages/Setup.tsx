import { useEffect, useState, type ReactNode } from "react";
import { useNavigate } from "react-router-dom";
import { ArrowRight, Camera, Check, Loader2, Mic, X } from "lucide-react";
import { usePractice } from "@/context/practice";
import { CameraFeed, type CameraStatus } from "@/components/CameraFeed";
import { MicLevel } from "@/components/MicLevel";
import { Button } from "@/components/Button";
import { Wordmark } from "@/components/Wordmark";
import { PRESENTATION_TYPES } from "@/types";
import { cn } from "@/lib/utils";

const MIC_DETAIL = {
  idle: "Waiting for permission",
  requesting: "Allow access in your browser",
  denied: "Blocked. Allow microphone access from the address bar.",
  unavailable: "No microphone found",
  ready: "Say something to test it",
} as const;

export default function Setup() {
  const navigate = useNavigate();
  const { kind, setKind, mic, stream, requestMic } = usePractice();
  const [camera, setCamera] = useState<CameraStatus>("connecting");

  useEffect(() => {
    if (mic === "idle") void requestMic();
  }, [mic, requestMic]);

  const micReady = mic === "ready";
  const cameraReady = camera === "live";
  const canStart = micReady || cameraReady;
  const warning =
    camera === "error" && micReady
      ? "Without a camera, only your voice will be analyzed."
      : cameraReady && (mic === "denied" || mic === "unavailable")
        ? "Without a microphone, only your body language will be analyzed."
        : null;

  return (
    <div className="min-h-screen">
      <header className="mx-auto max-w-6xl px-6 py-6">
        <Wordmark />
      </header>

      <main className="mx-auto grid max-w-6xl gap-14 px-6 pb-16 pt-4 lg:grid-cols-[minmax(0,5fr)_minmax(0,6fr)] lg:items-center">
        <div className="animate-rise">
          <h1 className="font-display text-5xl leading-[1.02] md:text-6xl">Practice your presentation</h1>
          <p className="mt-5 max-w-md text-[17px] leading-relaxed text-muted">
            Speak for 30 seconds to a few minutes. We'll follow your voice and posture on one timeline, then show you
            where they worked together and where they didn't.
          </p>

          <fieldset className="mt-10">
            <legend className="eyebrow">What are you practicing?</legend>
            <div className="mt-3 grid grid-cols-2 gap-2" role="radiogroup">
              {PRESENTATION_TYPES.map((type) => (
                <button
                  key={type.id}
                  role="radio"
                  aria-checked={kind === type.id}
                  onClick={() => setKind(type.id)}
                  className={cn(
                    "rounded-xl border px-4 py-3 text-left transition-colors",
                    kind === type.id ? "border-fg/70 bg-raised" : "border-line hover:border-faint",
                  )}
                >
                  <span className="block text-sm font-medium">{type.label}</span>
                  <span className="mt-0.5 block text-xs text-faint">{type.hint}</span>
                </button>
              ))}
            </div>
          </fieldset>

          <div className="mt-8 divide-y divide-line rounded-xl border border-line">
            <DeviceRow
              icon={<Camera className="h-4 w-4" />}
              label="Camera"
              state={camera === "live" ? "ready" : camera === "error" ? "error" : "checking"}
              detail={camera === "live" ? "Body tracking is on" : camera === "error" ? "Unavailable" : "Connecting…"}
            />
            <DeviceRow
              icon={<Mic className="h-4 w-4" />}
              label="Microphone"
              state={micReady ? "ready" : mic === "denied" || mic === "unavailable" ? "error" : "checking"}
              detail={MIC_DETAIL[mic]}
              trailing={
                micReady && stream ? (
                  <MicLevel stream={stream} />
                ) : mic === "denied" || mic === "unavailable" ? (
                  <button onClick={() => void requestMic()} className="text-sm font-medium text-fg hover:underline">
                    Retry
                  </button>
                ) : null
              }
            />
          </div>

          <div className="mt-10 flex flex-wrap items-center gap-x-5 gap-y-3">
            <Button disabled={!canStart} onClick={() => navigate("/practice")}>
              Start practice <ArrowRight className="h-4 w-4" />
            </Button>
            {warning && <p className="text-sm text-muted">{warning}</p>}
          </div>
        </div>

        <div className="animate-rise [animation-delay:120ms]">
          <CameraFeed onStatusChange={setCamera} />
          <p className="mt-3 text-sm text-faint">Keep your head, shoulders, and hands in frame. Standing works best.</p>
        </div>
      </main>
    </div>
  );
}

function DeviceRow({ icon, label, state, detail, trailing }: { icon: ReactNode; label: string; state: "checking" | "ready" | "error"; detail: string; trailing?: ReactNode }) {
  return (
    <div className="flex items-center gap-4 px-4 py-3.5">
      <span className="text-muted">{icon}</span>
      <div className="min-w-0 flex-1">
        <p className="text-sm font-medium">{label}</p>
        <p className={cn("truncate text-xs", state === "error" ? "text-attention" : "text-faint")}>{detail}</p>
      </div>
      {trailing}
      <span
        className={cn(
          "flex h-5 w-5 items-center justify-center rounded-full",
          state === "ready" && "bg-good/15 text-good",
          state === "error" && "bg-attention/15 text-attention",
          state === "checking" && "text-faint",
        )}
      >
        {state === "ready" && <Check className="h-3 w-3" strokeWidth={3} />}
        {state === "error" && <X className="h-3 w-3" strokeWidth={3} />}
        {state === "checking" && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
      </span>
    </div>
  );
}
