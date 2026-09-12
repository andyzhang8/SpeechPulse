import { useEffect, useState } from "react";
import { cn } from "@/lib/utils";

const BARS = [0.55, 0.85, 1, 0.75, 0.5];

export function MicLevel({ stream, showStatus }: { stream: MediaStream; showStatus?: boolean }) {
  const level = useAudioLevel(stream);
  return (
    <span className="inline-flex items-center gap-2.5">
      <span className="inline-flex h-4 items-center gap-[3px]" aria-hidden>
        {BARS.map((weight, i) => (
          <span
            key={i}
            className={cn("w-[3px] rounded-full transition-[height,background-color] duration-100", level > 0.08 ? "bg-voice" : "bg-line")}
            style={{ height: `${Math.max(3, Math.min(16, 16 * level * weight + 3))}px` }}
          />
        ))}
      </span>
      {showStatus && (level > 0.25 ? "Speaking" : "Listening")}
    </span>
  );
}

// mic loudness on dB scale (0..1), sampled ~12x/sec
function useAudioLevel(stream: MediaStream) {
  const [level, setLevel] = useState(0);

  useEffect(() => {
    const context = new AudioContext();
    const analyser = context.createAnalyser();
    analyser.fftSize = 1024;
    context.createMediaStreamSource(stream).connect(analyser);
    const samples = new Float32Array(analyser.fftSize);

    // AudioContext starts suspended, woken by first interaction
    const resume = () => void context.resume();
    window.addEventListener("pointerdown", resume, { once: true });

    let frame = 0;
    let last = 0;
    const tick = (now: number) => {
      frame = requestAnimationFrame(tick);
      if (now - last < 80) return;
      last = now;
      analyser.getFloatTimeDomainData(samples);
      const rms = Math.sqrt(samples.reduce((sum, v) => sum + v * v, 0) / samples.length);
      const db = 20 * Math.log10(rms || 1e-6);
      setLevel(Math.min(1, Math.max(0, (db + 55) / 45)));
    };
    frame = requestAnimationFrame(tick);

    return () => {
      cancelAnimationFrame(frame);
      window.removeEventListener("pointerdown", resume);
      void context.close();
    };
  }, [stream]);

  return level;
}
