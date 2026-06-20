// Transient flag-change notification. Replaces the always-on flag chip in the
// status bar: a toast slides in only when the race flag changes (e.g. GREEN →
// YELLOW → SC → RED and back), then auto-dismisses — keeping the nav bar clean.
import { useEffect, useRef, useState } from "react";

import { useRaceStore } from "../../store/raceStore";

const FLAG: Record<string, { label: string; note: string }> = {
  GREEN: { label: "GREEN FLAG", note: "track clear — racing resumes" },
  YELLOW: { label: "YELLOW FLAG", note: "hazard on track — no overtaking" },
  SC: { label: "SAFETY CAR", note: "field neutralised behind the safety car" },
  VSC: { label: "VIRTUAL SAFETY CAR", note: "delta times enforced" },
  RED: { label: "RED FLAG", note: "session stopped" },
  CHEQUERED: { label: "CHEQUERED FLAG", note: "session complete" },
};

export function FlagToast() {
  const flag = useRaceStore((s) => s.session?.flag ?? "GREEN");
  const sessionId = useRaceStore((s) => s.session?.session_id ?? null);
  const [toast, setToast] = useState<{ flag: string; id: number } | null>(null);
  const prev = useRef<string | null>(null);
  const prevSession = useRef<string | null>(null);

  useEffect(() => {
    // reset baseline (no toast) when the race changes or on first load
    if (prevSession.current !== sessionId) {
      prevSession.current = sessionId;
      prev.current = flag;
      return;
    }
    if (prev.current !== null && flag !== prev.current) {
      setToast({ flag, id: Date.now() });
    }
    prev.current = flag;
  }, [flag, sessionId]);

  useEffect(() => {
    if (!toast) return;
    const t = setTimeout(() => setToast(null), 4500);
    return () => clearTimeout(t);
  }, [toast]);

  if (!toast) return null;
  const info = FLAG[toast.flag] ?? { label: toast.flag, note: "" };
  return (
    <div className={`flag-toast flag-${toast.flag.toLowerCase()}`} key={toast.id} role="status">
      <span className="flag-toast-dot" />
      <div className="flag-toast-text">
        <b>{info.label}</b>
        {info.note && <em>{info.note}</em>}
      </div>
    </div>
  );
}
