import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { Check, ChevronDown, Info, Loader2, RotateCcw } from "lucide-react";
import { api, ApiError, joinSession, socket } from "@/lib/api";
import { clock, cn } from "@/lib/utils";
import type { Insight, Report, SessionStatus, Step, StepState, TimelineMoment } from "@/types";
import { Button } from "@/components/Button";
import { Wordmark } from "@/components/Wordmark";
import { InsightList, MainRecommendation } from "@/components/report/Insights";
import { MomentDetail, PresentationTimeline } from "@/components/report/Timeline";

const STEPS: { key: Step; label: string }[] = [
  { key: "speech", label: "Reviewing your speech" },
  { key: "body", label: "Analyzing body language" },
  { key: "connect", label: "Connecting delivery patterns" },
  { key: "report", label: "Building your coaching report" },
];
const PENDING: Record<Step, StepState> = { speech: "pending", body: "pending", connect: "pending", report: "pending" };
const LEGEND = [
  ["Voice", "bg-voice"],
  ["Body", "bg-body"],
  ["Strength", "bg-good"],
  ["Needs work", "bg-attention"],
];

export default function Results() {
  const { id = "" } = useParams();
  const navigate = useNavigate();
  const [steps, setSteps] = useState(PENDING);
  const [report, setReport] = useState<Report | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const load = () =>
      api
        .report(id)
        .then(setReport)
        .catch((err: unknown) => setError(err instanceof ApiError ? err.message : "Couldn't load the report."));
    const apply = (status: SessionStatus) => {
      setSteps(status.steps);
      if (status.status === "done") void load();
      if (status.status === "failed" || status.status === "abandoned") setError(status.error ?? "This session didn't finish.");
    };
    const onProgress = ({ step, status }: { step: Step; status: StepState }) => setSteps((prev) => ({ ...prev, [step]: status }));
    const onFailed = ({ error: message }: { error: string }) => setError(message);

    const leave = joinSession(id, apply);
    socket.on("analysis_progress", onProgress);
    socket.on("analysis_complete", load);
    socket.on("analysis_failed", onFailed);
    api
      .status(id)
      .then(apply)
      .catch((err: unknown) =>
        setError(err instanceof ApiError && err.status === 404 ? "This session is no longer available. The server may have restarted." : String(err)),
      );
    return () => {
      leave();
      socket.off("analysis_progress", onProgress);
      socket.off("analysis_complete", load);
      socket.off("analysis_failed", onFailed);
    };
  }, [id]);

  return (
    <div className="min-h-screen">
      <header className="mx-auto flex max-w-6xl items-center justify-between px-6 py-6">
        <Wordmark />
        {report && (
          <Button variant="secondary" onClick={() => navigate("/")} className="h-9 px-3.5">
            <RotateCcw className="h-3.5 w-3.5" /> Practice again
          </Button>
        )}
      </header>

      {error ? (
        <main className="mx-auto flex max-w-md flex-col items-start gap-6 px-6 pt-24">
          <h1 className="font-display text-4xl">We couldn't finish this analysis</h1>
          <p className="leading-relaxed text-muted">{error}</p>
          <Button onClick={() => navigate("/")}>Try another run</Button>
        </main>
      ) : report ? (
        <ReportView report={report} />
      ) : (
        <main className="px-6 pt-24">
          <AnalysisProgress steps={steps} />
        </main>
      )}
    </div>
  );
}
function AnalysisProgress({ steps }: { steps: Record<Step, StepState> }) {
  return (
    <div className="mx-auto w-full max-w-md animate-rise">
      <h1 className="font-display text-4xl">Analyzing your presentation</h1>
      <p className="mt-3 text-muted">This usually takes 15 to 40 seconds.</p>
      <ol className="mt-10 space-y-5">
        {STEPS.map(({ key, label }) => {
          const state = steps[key];
          return (
            <li key={key} className="flex items-center gap-4">
              <span
                className={cn(
                  "flex h-6 w-6 shrink-0 items-center justify-center rounded-full border",
                  state === "done" && "border-good/40 bg-good/15 text-good",
                  state === "active" && "border-fg/30 text-fg",
                  state === "pending" && "border-line",
                )}
              >
                {state === "done" && <Check className="h-3.5 w-3.5" strokeWidth={2.5} />}
                {state === "active" && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
              </span>
              <span className={cn("text-[15px] transition-colors", state === "pending" ? "text-faint" : "text-fg")}>{label}</span>
            </li>
          );
        })}
      </ol>
    </div>
  );
}


function ReportView({ report }: { report: Report }) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const timelineRef = useRef<HTMLElement>(null);
  const [playhead, setPlayhead] = useState<number | null>(null);
  const moments = report.timeline.moments;
  const [selectedId, setSelectedId] = useState<string | null>(
    () => (moments.find((m) => m.verdict === "needs_work") ?? moments[0])?.id ?? null,
  );
  const selectedIndex = useMemo(() => moments.findIndex((m) => m.id === selectedId), [moments, selectedId]);
  const selected = selectedIndex >= 0 ? moments[selectedIndex] : null;

  const seek = useCallback((time: number) => {
    const video = videoRef.current;
    if (!video) {
      setPlayhead(time);
      return;
    }
    video.currentTime = Math.max(0, time - 1);
    // play after click normally allowed; if blocked, native controls work
    video.play().catch(() => undefined);
  }, []);
  const select = useCallback(
    (moment: TimelineMoment) => {
      setSelectedId(moment.id);
      seek(moment.start);
    },
    [seek],
  );


  const open = useCallback(
    (insight: Insight) => {
      const moment = moments.find((m) => insight.moment_ids.includes(m.id));
      if (moment) select(moment);
      else if (insight.start !== null) seek(insight.start);
      timelineRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
    },
    [moments, select, seek],
  );

  return (
    <main className="mx-auto max-w-6xl space-y-16 px-6 pb-28 pt-6">
      <header className="grid items-end gap-10 md:grid-cols-[1fr_auto]">
        <div>
          <p className="eyebrow">
            {report.kind} · {clock(report.duration)}
          </p>
          <h1 className="mt-3 font-display text-5xl leading-none md:text-6xl">Presentation analysis</h1>
          <p className="mt-5 max-w-2xl text-lg leading-relaxed text-muted">{report.summary}</p>
        </div>
        {report.score && <ScoreDial {...report.score} />}
      </header>

      {report.notices.length > 0 && (
        <ul className="space-y-2">
          {report.notices.map((notice) => (
            <li key={notice} className="flex items-start gap-3 rounded-lg border border-line bg-surface px-4 py-3 text-sm text-muted">
              <Info className="mt-0.5 h-4 w-4 shrink-0 text-faint" />
              {notice}
            </li>
          ))}
        </ul>
      )}

      {report.main_recommendation && <MainRecommendation insight={report.main_recommendation} onOpen={open} />}

      <KeyMetrics metrics={report.metrics} />

      <section ref={timelineRef} className="scroll-mt-8">
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <h2 className="font-display text-3xl">Key moments</h2>
            <p className="mt-1 text-muted">Your voice and body on the same timeline. Select a marker to see what happened.</p>
          </div>
          <ul className="flex flex-wrap gap-x-5 gap-y-2 text-xs text-muted">
            {LEGEND.map(([label, tone]) => (
              <li key={label} className="inline-flex items-center gap-2">
                <span className={`h-2 w-2 rounded-full ${tone}`} />
                {label}
              </li>
            ))}
          </ul>
        </div>

        <div className="mt-8">
          <PresentationTimeline timeline={report.timeline} selectedId={selectedId} playhead={playhead} onSelect={select} onSeek={seek} />
        </div>

        <div className="mt-8 grid gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
          {report.video_url && (
            <video
              ref={videoRef}
              src={report.video_url}
              controls
              playsInline
              preload="metadata"
              onTimeUpdate={(event) => setPlayhead(event.currentTarget.currentTime)}
              className="aspect-[4/3] w-full rounded-2xl bg-black ring-1 ring-line"
            />
          )}
          {selected ? (
            <MomentDetail
              moment={selected}
              index={selectedIndex}
              total={moments.length}
              onStep={(delta) => select(moments[selectedIndex + delta])}
              onPlay={seek}
              canPlay={Boolean(report.video_url)}
            />
          ) : (
            <p className="rounded-2xl border border-line p-6 text-muted">No standout moments were detected in this run.</p>
          )}
        </div>
      </section>

      <div className="grid gap-14 md:grid-cols-2">
        <InsightList title="Strengths" tone="good" items={report.strengths} empty="Keep practicing to build up strengths." onOpen={open} />
        <InsightList title="Areas to improve" tone="attention" items={report.improvements} empty="No sustained issues were detected." onOpen={open} />
      </div>

      <section>
        <h2 className="eyebrow">Practice plan</h2>
        <ol className="mt-4 grid gap-4 md:grid-cols-3">
          {report.practice_plan.map((item, i) => (
            <li key={item} className="rounded-xl border border-line p-6">
              <span className="font-display text-4xl leading-none text-faint">{i + 1}</span>
              <p className="mt-4 leading-relaxed">{item}</p>
            </li>
          ))}
        </ol>
      </section>

      {report.transcript.length > 0 && (
        <details className="group border-t border-line pt-6">
          <summary className="flex cursor-pointer list-none items-center gap-2 text-sm font-medium text-muted hover:text-fg">
            <ChevronDown className="h-4 w-4 transition-transform group-open:rotate-180" />
            Full transcript
          </summary>
          <ol className="mt-5 space-y-3">
            {report.transcript.map((segment) => (
              <li key={segment.start} className="grid grid-cols-[3.5rem_1fr] gap-4 leading-relaxed">
                <button onClick={() => seek(segment.start)} className="tabular text-left text-sm text-faint hover:text-fg">
                  {clock(segment.start)}
                </button>
                <p className="text-muted">{segment.text}</p>
              </li>
            ))}
          </ol>
        </details>
      )}
    </main>
  );
}

function ScoreDial({ overall, voice, body }: NonNullable<Report["score"]>) {
  const radius = 54;
  const circumference = 2 * Math.PI * radius;
  const parts: [string, number | null, string][] = [
    ["Voice", voice, "bg-voice"],
    ["Body", body, "bg-body"],
  ];
  return (
    <div className="flex items-center gap-6">
      <div className="relative h-32 w-32">
        <svg viewBox="0 0 128 128" className="h-full w-full -rotate-90">
          <circle cx="64" cy="64" r={radius} fill="none" strokeWidth="3" className="stroke-line" />
          <circle
            cx="64"
            cy="64"
            r={radius}
            fill="none"
            strokeWidth="3"
            strokeLinecap="round"
            className="stroke-fg transition-[stroke-dashoffset] duration-1000"
            strokeDasharray={circumference}
            strokeDashoffset={circumference * (1 - overall / 100)}
          />
        </svg>
        <div className="absolute inset-0 flex flex-col items-center justify-center">
          <span className="font-display text-5xl leading-none">{overall}</span>
          <span className="mt-1 text-xs text-faint">of 100</span>
        </div>
      </div>
      <dl className="space-y-2 text-sm">
        {parts.map(([label, value, tone]) => (
          <div key={label} className="flex items-center gap-2.5">
            <span className={`h-1.5 w-1.5 rounded-full ${tone}`} />
            <dt className="w-10 text-muted">{label}</dt>
            <dd className="tabular font-medium">{value ?? "—"}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

function KeyMetrics({ metrics }: { metrics: Report["metrics"] }) {
  const items: { label: string; value: string | null; detail: string }[] = [
    { label: "Pace", value: metrics.wpm !== null ? `${metrics.wpm}` : null, detail: metrics.wpm !== null ? "words per minute" : "Not analyzed" },
    {
      label: "Fillers",
      value: metrics.filler_count !== null ? `${metrics.filler_count}` : null,
      detail: metrics.fillers_per_minute !== null ? `${metrics.fillers_per_minute} per minute` : "Not analyzed",
    },
    {
      label: "Posture",
      value: metrics.posture_stability !== null ? `${metrics.posture_stability}%` : null,
      detail: metrics.posture_stability !== null ? "of the time stable" : "Not analyzed",
    },
    { label: "Movement", value: metrics.movement, detail: metrics.movement ? "hand activity" : "Not analyzed" },
    { label: "Vocal variety", value: metrics.vocal_variety, detail: metrics.vocal_variety ? "pitch variation" : "Not analyzed" },
  ];

  return (
    <dl className="grid grid-cols-2 gap-y-8 border-y border-line py-8 sm:grid-cols-3 lg:grid-cols-5">
      {items.map(({ label, value, detail }) => (
        <div key={label} className="px-1 lg:border-l lg:border-line lg:px-6 lg:first:border-l-0 lg:first:pl-0">
          <dt className="eyebrow">{label}</dt>
          <dd className="tabular mt-2 text-3xl font-medium tracking-tight">{value ?? "—"}</dd>
          <dd className="mt-1 text-sm text-faint">{detail}</dd>
        </div>
      ))}
    </dl>
  );
}
