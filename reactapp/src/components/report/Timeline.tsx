import { useMemo, useState, type HTMLAttributes, type MouseEvent, type ReactNode } from "react";
import { ChevronLeft, ChevronRight, Play } from "lucide-react";
import type { PaceWindow, PresentationEvent, Timeline, TimelineMoment } from "@/types";
import { clock, cn, timeRange } from "@/lib/utils";
import { Button } from "@/components/Button";

const PACE_MIN = 70;
const PACE_MAX = 220;
const COMFORT = [120, 160] as const;
const VOICE_BARS = new Set(["high_pace", "low_pace", "filler_cluster", "monotone", "vocal_variety"]);

interface Hover {
  left: number;
  title: string;
  detail: string;
}

interface TimelineProps {
  timeline: Timeline;
  selectedId: string | null;
  playhead: number | null;
  onSelect: (moment: TimelineMoment) => void;
  onSeek: (time: number) => void;
}

// voice, body, coaching on shared clock so moments line up visually
export function PresentationTimeline({ timeline, selectedId, playhead, onSelect, onSeek }: TimelineProps) {
  const { duration } = timeline;
  const [hover, setHover] = useState<Hover | null>(null);
  const ticks = useMemo(() => axisTicks(duration), [duration]);

  const percent = (t: number) => (Math.min(Math.max(t, 0), duration) / duration) * 100;
  const place = (start: number, end: number) => ({
    left: `${percent(start)}%`,
    width: `${Math.max(percent(end) - percent(start), 0.7)}%`,
  });
  const hoverable = (time: number, title: string, detail: string) => ({
    onMouseEnter: () => setHover({ left: percent(time), title, detail }),
    onMouseLeave: () => setHover(null),
  });
  const timeAt = (event: MouseEvent<HTMLDivElement>) => {
    const rect = event.currentTarget.getBoundingClientRect();
    return ((event.clientX - rect.left) / rect.width) * duration;
  };

  const showPace = (event: MouseEvent<HTMLDivElement>) => {
    if (event.target !== event.currentTarget && !(event.target instanceof SVGElement)) return;
    const t = timeAt(event);
    const window = nearestWindow(timeline.pace, t);
    if (window) setHover({ left: percent(t), title: `${window.wpm} WPM`, detail: clock(t) });
  };

  const selected = timeline.moments.find((m) => m.id === selectedId);
  const eventBar = (e: PresentationEvent, tone: string) => (
    <button
      key={`${e.type}-${e.start}`}
      onClick={(event) => {
        event.stopPropagation();
        const moment = timeline.moments.find((m) => m.start < e.end && m.end > e.start);
        if (moment) onSelect(moment);
        else onSeek(e.start);
      }}
      className={cn("absolute top-1/2 h-2.5 -translate-y-1/2 rounded-full transition-opacity hover:opacity-100", tone)}
      style={{ ...place(e.start, e.end), opacity: 0.5 + 0.5 * Math.max(e.severity, 0.3) }}
      aria-label={`${e.label}, ${timeRange(e.start, e.end)}`}
      {...hoverable((e.start + e.end) / 2, e.label, timeRange(e.start, e.end))}
    />
  );

  return (
    <div className="flex gap-4 select-none">
      <div className="w-14 shrink-0 text-right">
        <TrackLabel className="h-16">Voice</TrackLabel>
        <TrackLabel className="h-11">Body</TrackLabel>
        <TrackLabel className="h-11">Coach</TrackLabel>
      </div>

      <div className="relative min-w-0 flex-1">
        <Track className="h-16" onClick={(e) => onSeek(timeAt(e))} onMouseMove={showPace} onMouseLeave={() => setHover(null)}>
          <PaceLine pace={timeline.pace} duration={duration} />
          <div className="absolute inset-x-0 bottom-0 h-5">
            {timeline.voice.filter((e) => VOICE_BARS.has(e.type)).map((e) => eventBar(e, e.type === "vocal_variety" ? "bg-voice/40" : "bg-voice"))}
            {timeline.voice
              .filter((e) => e.type === "filler")
              .map((e) => (
                <span
                  key={`filler-${e.start}`}
                  className="absolute top-1/2 h-3.5 w-[3px] -translate-x-1/2 -translate-y-1/2 rounded-full bg-voice ring-2 ring-surface"
                  style={{ left: `${percent(e.start)}%` }}
                  {...hoverable(e.start, `Filler ${e.label}`, clock(e.start))}
                />
              ))}
          </div>
        </Track>

        <Track className="h-11" onClick={(e) => onSeek(timeAt(e))}>
          {timeline.body.map((e) => eventBar(e, e.type === "out_of_frame" ? "bg-faint/50" : "bg-body"))}
        </Track>

        <Track className="h-11" onClick={(e) => onSeek(timeAt(e))}>
          {timeline.moments.map((m) => (
            <span
              key={`span-${m.id}`}
              className={cn("absolute top-1/2 h-px -translate-y-1/2", m.verdict === "strength" ? "bg-good/50" : "bg-attention/50")}
              style={place(m.start, m.end)}
            />
          ))}
          {timeline.moments.map((m) => (
            <button
              key={m.id}
              onClick={(event) => {
                event.stopPropagation();
                onSelect(m);
              }}
              className="absolute top-1/2 -translate-x-1/2 -translate-y-1/2 p-1.5"
              style={{ left: `${percent((m.start + m.end) / 2)}%` }}
              aria-label={`${m.title}, ${timeRange(m.start, m.end)}`}
              {...hoverable((m.start + m.end) / 2, m.title, timeRange(m.start, m.end))}
            >
              <span
                className={cn(
                  "block h-3.5 w-3.5 rounded-full ring-4 ring-surface transition-transform duration-200",
                  m.verdict === "strength" ? "bg-good" : "bg-attention",
                  m.id === selectedId ? "scale-[1.35]" : "hover:scale-125",
                )}
              />
            </button>
          ))}
        </Track>

        <div className="relative mt-2 h-4">
          {ticks.map((t) => (
            <span
              key={t}
              className={cn("tabular absolute text-[11px] text-faint", t > 0 && "-translate-x-1/2")}
              style={{ left: `${percent(t)}%` }}
            >
              {clock(t)}
            </span>
          ))}
        </div>

        <div className="pointer-events-none absolute inset-x-0 top-0 h-[152px]">
          {selected && (
            <div className="absolute inset-y-0 rounded-md bg-fg/[0.07] ring-1 ring-inset ring-fg/15" style={place(selected.start, selected.end)} />
          )}
          {playhead !== null && <div className="absolute inset-y-0 w-px bg-fg/80" style={{ left: `${percent(playhead)}%` }} />}
          {hover && (
            <div
              className="absolute -top-2 z-10 -translate-x-1/2 -translate-y-full whitespace-nowrap rounded-md border border-line bg-raised px-2.5 py-1.5 text-xs shadow-xl"
              style={{ left: `${Math.min(Math.max(hover.left, 6), 94)}%` }}
            >
              <p className="font-medium text-fg">{hover.title}</p>
              <p className="tabular text-muted">{hover.detail}</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function TrackLabel({ className, children }: { className: string; children: ReactNode }) {
  return <div className={cn("eyebrow flex items-center justify-end", className)}>{children}</div>;
}

function Track({ className, children, ...handlers }: { className: string; children: ReactNode } & HTMLAttributes<HTMLDivElement>) {
  return (
    <div className={cn("relative cursor-pointer border-b border-line/70 bg-surface first:rounded-t-lg last:rounded-b-lg", className)} {...handlers}>
      {children}
    </div>
  );
}

function PaceLine({ pace, duration }: { pace: PaceWindow[]; duration: number }) {
  if (pace.length < 2) return null;
  const y = (wpm: number) => 100 - ((Math.min(Math.max(wpm, PACE_MIN), PACE_MAX) - PACE_MIN) / (PACE_MAX - PACE_MIN)) * 100;
  const points = pace.map((w) => `${(((w.start + w.end) / 2 / duration) * 1000).toFixed(1)},${y(w.wpm).toFixed(1)}`);
  return (
    <svg viewBox="0 0 1000 100" preserveAspectRatio="none" className="absolute inset-x-0 top-1.5 h-10 w-full">
      <rect x="0" width="1000" y={y(COMFORT[1])} height={y(COMFORT[0]) - y(COMFORT[1])} className="fill-fg/[0.045]" />
      <path
        d={`M${points.join("L")}`}
        fill="none"
        className="stroke-voice/80"
        strokeWidth="1.5"
        strokeLinejoin="round"
        vectorEffect="non-scaling-stroke"
      />
    </svg>
  );
}

function nearestWindow(pace: PaceWindow[], t: number) {
  return pace.reduce<PaceWindow | null>((best, w) => {
    const distance = Math.abs((w.start + w.end) / 2 - t);
    return !best || distance < Math.abs((best.start + best.end) / 2 - t) ? w : best;
  }, null);
}

function axisTicks(duration: number) {
  const step = [5, 10, 15, 30, 60, 120].find((s) => duration / s <= 8) ?? 300;
  const ticks: number[] = [];
  for (let t = 0; t <= duration - step / 3; t += step) ticks.push(t);
  return ticks;
}

interface DetailProps {
  moment: TimelineMoment;
  index: number;
  total: number;
  onStep: (delta: number) => void;
  onPlay: (time: number) => void;
  canPlay: boolean;
}

export function MomentDetail({ moment, index, total, onStep, onPlay, canPlay }: DetailProps) {
  const strength = moment.verdict === "strength";
  return (
    <article key={moment.id} className="flex h-full animate-rise flex-col rounded-2xl border border-line bg-surface p-6">
      <div className="flex items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <span
            className={cn(
              "rounded-md px-2 py-1 text-[11px] font-medium uppercase tracking-[0.1em]",
              strength ? "bg-good/15 text-good" : "bg-attention/15 text-attention",
            )}
          >
            {strength ? "Strength" : "Needs work"}
          </span>
          <span className="tabular text-sm text-muted">{timeRange(moment.start, moment.end)}</span>
        </div>
        <div className="flex items-center gap-1 text-sm text-faint">
          <button onClick={() => onStep(-1)} disabled={index === 0} className="rounded p-1 hover:text-fg disabled:opacity-30" aria-label="Previous moment">
            <ChevronLeft className="h-4 w-4" />
          </button>
          <span className="tabular">
            {index + 1} / {total}
          </span>
          <button onClick={() => onStep(1)} disabled={index === total - 1} className="rounded p-1 hover:text-fg disabled:opacity-30" aria-label="Next moment">
            <ChevronRight className="h-4 w-4" />
          </button>
        </div>
      </div>

      <h3 className="mt-4 font-display text-3xl leading-tight">{moment.title}</h3>

      {moment.transcript && (
        <blockquote className="mt-4 border-l-2 border-line pl-4 text-[15px] italic leading-relaxed text-muted">
          “{moment.transcript}”
        </blockquote>
      )}

      <div className="mt-5 grid gap-5 sm:grid-cols-2">
        <Signals label="Voice" tone="bg-voice" items={moment.speech} />
        <Signals label="Body" tone="bg-body" items={moment.posture} />
      </div>

      <p className="mt-5 leading-relaxed">{moment.coaching}</p>

      {canPlay && (
        <div className="mt-auto pt-6">
          <Button variant="secondary" onClick={() => onPlay(moment.start)} className="h-9 px-3.5">
            <Play className="h-3.5 w-3.5 fill-current" /> Replay this moment
          </Button>
        </div>
      )}
    </article>
  );
}

function Signals({ label, tone, items }: { label: string; tone: string; items: string[] }) {
  return (
    <div>
      <p className="eyebrow flex items-center gap-2">
        <span className={cn("h-1.5 w-1.5 rounded-full", tone)} />
        {label}
      </p>
      <ul className="mt-2 space-y-1 text-sm">
        {items.length ? items.map((item) => <li key={item}>{item}</li>) : <li className="text-faint">Nothing notable</li>}
      </ul>
    </div>
  );
}
