import { Play } from "lucide-react";
import type { Insight } from "@/types";
import { cn, timeRange } from "@/lib/utils";

type OpenInsight = (insight: Insight) => void;

export function MainRecommendation({ insight, onOpen }: { insight: Insight; onOpen: OpenInsight }) {
  return (
    <section className="animate-rise rounded-2xl bg-fg px-8 py-9 text-canvas md:px-10">
      <p className="text-[11px] font-medium uppercase tracking-[0.14em] text-canvas/55">Fix this first</p>
      <h2 className="mt-3 max-w-3xl font-display text-4xl leading-tight">{insight.title}</h2>
      <p className="mt-4 max-w-3xl text-[17px] leading-relaxed text-canvas/80">{insight.description}</p>
      <div className="mt-6 flex flex-wrap items-center gap-x-5 gap-y-3">
        <TimeChip insight={insight} onOpen={onOpen} inverted />
        <Evidence insight={insight} inverted />
      </div>
    </section>
  );
}

interface ListProps {
  title: string;
  tone: "good" | "attention";
  items: Insight[];
  empty: string;
  onOpen: OpenInsight;
}

export function InsightList({ title, tone, items, empty, onOpen }: ListProps) {
  return (
    <section>
      <h2 className="eyebrow flex items-center gap-2">
        <span className={cn("h-1.5 w-1.5 rounded-full", tone === "good" ? "bg-good" : "bg-attention")} />
        {title}
      </h2>
      {items.length === 0 ? (
        <p className="mt-4 border-t border-line pt-5 text-muted">{empty}</p>
      ) : (
        <ul className="mt-4 divide-y divide-line border-t border-line">
          {items.map((item) => (
            <li key={item.title} className="py-6">
              <div className="flex items-start justify-between gap-4">
                <h3 className="text-lg font-medium leading-snug">{item.title}</h3>
                <TimeChip insight={item} onOpen={onOpen} />
              </div>
              <p className="mt-2 leading-relaxed text-muted">{item.description}</p>
              <div className="mt-3">
                <Evidence insight={item} />
              </div>
              {item.try_next && (
                <p className="mt-4 text-[15px] leading-relaxed">
                  <span className="text-faint">Try next — </span>
                  {item.try_next}
                </p>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function TimeChip({ insight, onOpen, inverted }: { insight: Insight; onOpen: OpenInsight; inverted?: boolean }) {
  if (insight.start === null || insight.end === null) return null;
  return (
    <button
      onClick={() => onOpen(insight)}
      className={cn(
        "tabular inline-flex h-7 shrink-0 items-center gap-1.5 rounded-md px-2.5 text-xs font-medium transition-colors",
        inverted ? "bg-canvas/10 text-canvas hover:bg-canvas/15" : "bg-raised text-fg hover:bg-line",
      )}
    >
      <Play className="h-3 w-3 fill-current" />
      {timeRange(insight.start, insight.end)}
    </button>
  );
}

// measured signals behind coaching, color-coded by modality
function Evidence({ insight, inverted }: { insight: Insight; inverted?: boolean }) {
  const items = [
    ...insight.speech_evidence.map((text) => ({ text, tone: "bg-voice" })),
    ...insight.posture_evidence.map((text) => ({ text, tone: "bg-body" })),
  ];
  if (!items.length) return null;
  return (
    <ul className="flex flex-wrap gap-x-5 gap-y-1.5">
      {items.map(({ text, tone }) => (
        <li key={text} className={cn("inline-flex items-center gap-2 text-sm", inverted ? "text-canvas/75" : "text-muted")}>
          <span className={cn("h-1.5 w-1.5 shrink-0 rounded-full", tone)} />
          {text}
        </li>
      ))}
    </ul>
  );
}
