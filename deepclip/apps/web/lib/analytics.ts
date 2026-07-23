import { API_BASE } from "./api";
import { getAnonId, uuid } from "./anon";

/**
 * Client analytics beacon (master doc D4/D8).
 *
 * The product's entire go/no-go is "do users finish pages and come back?" so the
 * events that answer it have to be captured. Design constraints:
 *
 * - **Anonymous.** anon_id is a random UUID in localStorage; session_id is
 *   per-tab. No login, no PII — completion and return are measurable without
 *   identifying anyone.
 * - **Never blocks or breaks the page.** Events are buffered and flushed with
 *   `sendBeacon`, which is fire-and-forget and survives the page being closed.
 *   Every call is wrapped so analytics can never throw into the UI.
 * - **Batched.** One request per burst, not per interaction.
 */

type EventKind =
  | "page_view"
  | "clip_view"
  | "clip_complete"
  | "page_complete"
  | "end_card"
  | "satisfaction"
  | "import"
  | "report";

type Event = {
  anon_id: string;
  session_id: string;
  kind: EventKind;
  slug?: string;
  mode?: string;
  video_id?: string;
  position?: number;
  value?: number;
  meta?: Record<string, unknown>;
};

const FLUSH_MS = 4000;
const MAX_BUFFER = 20;

// One session id per tab load. Module-scoped so every event in a page view
// shares it, which is what makes completion-per-session meaningful.
const SESSION_ID = uuid();

let buffer: Event[] = [];
let timer: ReturnType<typeof setTimeout> | null = null;

function flush(useBeacon = false): void {
  if (buffer.length === 0 || typeof window === "undefined") return;
  const batch = { events: buffer };
  buffer = [];
  if (timer) {
    clearTimeout(timer);
    timer = null;
  }

  const url = `${API_BASE}/api/events`;
  try {
    if (useBeacon && navigator.sendBeacon) {
      // sendBeacon is the only transport that reliably survives page unload.
      navigator.sendBeacon(url, new Blob([JSON.stringify(batch)], { type: "application/json" }));
      return;
    }
    fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(batch),
      keepalive: true,
    }).catch(() => {
      /* analytics must never surface an error to the user */
    });
  } catch {
    /* swallow — losing an event is acceptable, breaking the page is not */
  }
}

export function track(
  kind: EventKind,
  fields: Omit<Event, "anon_id" | "session_id" | "kind"> = {}
): void {
  if (typeof window === "undefined") return;
  try {
    buffer.push({ anon_id: getAnonId(), session_id: SESSION_ID, kind, ...fields });
    if (buffer.length >= MAX_BUFFER) {
      flush();
      return;
    }
    if (!timer) timer = setTimeout(() => flush(), FLUSH_MS);
  } catch {
    /* never throw */
  }
}

// Flush whatever is buffered when the tab goes away — otherwise the most
// important event (reaching the end) is the one most likely to be lost.
if (typeof window !== "undefined") {
  window.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "hidden") flush(true);
  });
  window.addEventListener("pagehide", () => flush(true));
}
