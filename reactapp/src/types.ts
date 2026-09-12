// Shapes returned by the Flask API; see schemas.py.

export type Verdict = "strength" | "needs_work";

export interface PresentationEvent {
  type: string;
  category: "speech" | "posture";
  start: number;
  end: number;
  severity: number;
  label: string;
  metadata: Record<string, unknown>;
}

export interface PaceWindow {
  start: number;
  end: number;
  wpm: number;
}

export interface TimelineMoment {
  id: string;
  kind: "combined" | "speech" | "posture" | "steady";
  start: number;
  end: number;
  transcript: string;
  speech: string[];
  posture: string[];
  verdict: Verdict;
  title: string;
  coaching: string;
}

export interface Timeline {
  duration: number;
  voice: PresentationEvent[];
  body: PresentationEvent[];
  pace: PaceWindow[];
  moments: TimelineMoment[];
}

export interface Insight {
  title: string;
  description: string;
  start: number | null;
  end: number | null;
  moment_ids: string[];
  speech_evidence: string[];
  posture_evidence: string[];
  try_next: string | null;
}

export interface Report {
  session_id: string;
  kind: string;
  duration: number;
  score: { overall: number; voice: number | null; body: number | null } | null;
  summary: string;
  main_recommendation: Insight | null;
  metrics: {
    wpm: number | null;
    filler_count: number | null;
    fillers_per_minute: number | null;
    posture_stability: number | null;
    movement: string | null;
    vocal_variety: string | null;
  };
  strengths: Insight[];
  improvements: Insight[];
  practice_plan: string[];
  timeline: Timeline;
  transcript: { start: number; end: number; text: string }[];
  notices: string[];
  video_url: string | null;
  ai_coached: boolean;
}

export type Step = "speech" | "body" | "connect" | "report";
export type StepState = "pending" | "active" | "done";

export interface SessionStatus {
  id: string;
  kind: string;
  status: "recording" | "processing" | "done" | "failed" | "abandoned";
  steps: Record<Step, StepState>;
  error: string | null;
}

export interface LiveMetrics {
  elapsed: number;
  visible: boolean;
  posture?: string;
  movement?: string;
  arms?: string;
  alignment?: string;
}

export type PresentationKind = "presentation" | "interview" | "pitch" | "class";

export const PRESENTATION_TYPES: { id: PresentationKind; label: string; hint: string }[] = [
  { id: "presentation", label: "Presentation", hint: "Talks and team updates" },
  { id: "interview", label: "Interview answer", hint: "Answering one question" },
  { id: "pitch", label: "Pitch", hint: "Persuading in a few minutes" },
  { id: "class", label: "Class presentation", hint: "Presenting to a class" },
];
