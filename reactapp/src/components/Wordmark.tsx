import { Link } from "react-router-dom";

export function Wordmark() {
  return (
    <Link to="/" className="inline-flex items-center gap-2 text-[15px] font-medium tracking-tight text-fg">
      <svg viewBox="0 0 32 32" className="h-5 w-5" aria-hidden>
        <path d="M4 17h6l3-7 4 13 3-9 2 3h6" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
      SpeechPulse
    </Link>
  );
}
