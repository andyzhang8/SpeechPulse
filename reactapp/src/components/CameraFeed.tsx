import { useEffect, useRef, useState, type ReactNode } from "react";
import { CameraOff, RotateCw } from "lucide-react";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";

export type CameraStatus = "connecting" | "live" | "error";

interface Props {
  onStatusChange?: (status: CameraStatus) => void;
  className?: string;
  children?: ReactNode;
}

// server-analyzed MJPEG - backend captures, tracks pose, annotates
export function CameraFeed({ onStatusChange, className, children }: Props) {
  const imageRef = useRef<HTMLImageElement>(null);
  const [attempt, setAttempt] = useState(0);
  const [status, setStatus] = useState<CameraStatus>("connecting");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => onStatusChange?.(status), [status, onStatusChange]);

  // browsers fire `load` inconsistently for MJPEG, so poll for first decoded frame
  useEffect(() => {
    if (status !== "connecting") return;
    const timer = setInterval(() => {
      if (imageRef.current?.complete && imageRef.current.naturalWidth > 0) setStatus("live");
    }, 200);
    return () => clearInterval(timer);
  }, [status, attempt]);

  const handleError = async () => {
    setStatus("error");
    try {
      const info = await api.camera();
      setError(info.error ?? "The camera stream was interrupted.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "The camera stream was interrupted.");
    }
  };

  const retry = () => {
    setStatus("connecting");
    setError(null);
    setAttempt((n) => n + 1);
  };

  return (
    <div className={cn("relative aspect-[4/3] overflow-hidden rounded-2xl bg-surface ring-1 ring-line", className)}>
      {status !== "error" && (
        <img
          ref={imageRef}
          key={attempt}
          src={`/video_feed?attempt=${attempt}`}
          alt="Your camera, with body tracking"
          onError={handleError}
          className={cn("h-full w-full object-cover transition-opacity duration-500", status === "live" ? "opacity-100" : "opacity-0")}
        />
      )}

      {status === "connecting" && (
        <div className="absolute inset-0 flex items-center justify-center">
          <p className="animate-pulse text-sm text-muted">Connecting to camera…</p>
        </div>
      )}

      {status === "error" && (
        <div className="absolute inset-0 flex flex-col items-center justify-center gap-4 px-10 text-center">
          <CameraOff className="h-7 w-7 text-faint" />
          <p className="max-w-sm text-sm leading-relaxed text-muted">{error}</p>
          <button onClick={retry} className="inline-flex items-center gap-2 text-sm font-medium text-fg hover:underline">
            <RotateCw className="h-4 w-4" /> Try again
          </button>
        </div>
      )}

      {status === "live" && children}
    </div>
  );
}
