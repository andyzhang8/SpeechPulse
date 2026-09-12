import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from "react";
import type { PresentationKind } from "@/types";

export type MicState = "idle" | "requesting" | "ready" | "denied" | "unavailable";

interface PracticeContextValue {
  kind: PresentationKind;
  setKind: (kind: PresentationKind) => void;
  mic: MicState;
  stream: MediaStream | null;
  requestMic: () => Promise<void>;
  releaseMic: () => void;
}

const PracticeContext = createContext<PracticeContextValue | null>(null);

// carries presentation type + mic stream from setup to session
export function PracticeProvider({ children }: { children: ReactNode }) {
  const [kind, setKind] = useState<PresentationKind>("presentation");
  const [mic, setMic] = useState<MicState>("idle");
  const [stream, setStream] = useState<MediaStream | null>(null);

  const requestMic = useCallback(async () => {
    if (!navigator.mediaDevices?.getUserMedia) {
      setMic("unavailable");
      return;
    }
    setMic("requesting");
    try {
      const next = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } });
      next.getAudioTracks()[0]?.addEventListener("ended", () => {
        setStream(null);
        setMic("unavailable");
      });
      setStream(next);
      setMic("ready");
    } catch (err) {
      const blocked = err instanceof DOMException && (err.name === "NotAllowedError" || err.name === "SecurityError");
      setMic(blocked ? "denied" : "unavailable");
    }
  }, []);

  const releaseMic = useCallback(() => {
    setStream((current) => {
      current?.getTracks().forEach((track) => track.stop());
      return null;
    });
    setMic("idle");
  }, []);

  const value = useMemo(
    () => ({ kind, setKind, mic, stream, requestMic, releaseMic }),
    [kind, mic, stream, requestMic, releaseMic],
  );
  return <PracticeContext.Provider value={value}>{children}</PracticeContext.Provider>;
}

// eslint-disable-next-line react-refresh/only-export-components
export function usePractice() {
  const context = useContext(PracticeContext);
  if (!context) throw new Error("usePractice must be used inside PracticeProvider");
  return context;
}
