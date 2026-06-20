import { useRaceStore } from "../../store/raceStore";

export type Page = "replay" | "live";

/** Persistent top-level navigation: two pages, Replay and Live. Always visible
 *  so the user can switch at any time (the Live page is reachable even when no
 *  race is live — it shows a waiting/standby screen). */
export function PageTabs({ page, onChange, liveAvailable }: {
  page: Page;
  onChange: (p: Page) => void;
  liveAvailable: boolean;
}) {
  // a real live session is currently streaming (vs. token set but track idle)
  const liveStreaming = useRaceStore(
    (s) => s.session?.mode === "live" && !/no live/i.test(s.session?.name ?? ""),
  );

  return (
    <nav className="page-tabs" aria-label="Pages">
      <div className="page-tabs-brand">
        <span className="page-tabs-mark">🏎</span> Sport Analyzer
      </div>
      <div className="page-tabs-group" role="tablist">
        <button
          role="tab"
          aria-selected={page === "replay"}
          className={`page-tab${page === "replay" ? " active" : ""}`}
          onClick={() => onChange("replay")}
        >
          <span className="page-tab-icon">▦</span> Replay
        </button>
        <button
          role="tab"
          aria-selected={page === "live"}
          className={`page-tab page-tab-live${page === "live" ? " active" : ""}`}
          onClick={() => onChange("live")}
          title={liveAvailable ? "Live race timing" : "Live needs an OpenF1 token"}
        >
          <span className={`page-tab-dot${liveStreaming ? " on" : ""}`} /> Live
        </button>
      </div>
    </nav>
  );
}
