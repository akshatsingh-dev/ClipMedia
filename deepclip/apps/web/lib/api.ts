import type { IndexEntry, Page } from "./types";

/**
 * API client with fixture fallback (DECISIONS D4).
 *
 * When the FastAPI gateway is reachable it is the source of truth. When it is
 * not — the common case during frontend work, since the pipeline needs API keys
 * and Postgres — the app falls back to fixture JSON so the product is still
 * viewable. The banner in the UI makes clear which one you are looking at.
 */

export const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE || "http://localhost:8000";

const TIMEOUT_MS = 2500;

async function tryFetch(path: string): Promise<Response | null> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), TIMEOUT_MS);
  try {
    const res = await fetch(`${API_BASE}${path}`, {
      signal: controller.signal,
      cache: "no-store",
    });
    return res.ok ? res : null;
  } catch {
    // API down: fixtures take over. Not an error worth surfacing.
    return null;
  } finally {
    clearTimeout(timer);
  }
}

export async function fetchIndex(): Promise<IndexEntry[] | null> {
  const res = await tryFetch("/api/pages");
  if (!res) return null;
  const data = await res.json();
  return (data.pages || []).map((p: any) => ({
    slug: p.slug,
    title: p.title || p.slug,
    subtitle: "",
    mode: p.mode,
    query: p.slug,
    clip_count: 0,
  }));
}

export async function fetchPage(slug: string): Promise<Page | null> {
  const res = await tryFetch(`/api/pages/${encodeURIComponent(slug)}`);
  if (!res) return null;
  const data = await res.json();
  return {
    ...data.page,
    slug,
    mode: data.mode,
    query: data.query,
    timestamps_verified: true,
    source_note: "",
  };
}

export type BuildStart = {
  cached: boolean;
  slug: string;
  page?: Page;
  status?: string;
  joined?: boolean;
};

export async function startBuild(
  query: string,
  mode?: "learn" | "entertain"
): Promise<BuildStart> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE}/api/build`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query, mode }),
    });
  } catch {
    // A dead API surfaces as a bare "Failed to fetch", which tells the user
    // nothing. Right now the API being down is the expected state.
    throw new Error(
      `Can't reach the build API at ${API_BASE}. Live building needs the ` +
        `FastAPI gateway, a worker, Postgres, Redis, and both API keys. ` +
        `The prebuilt pages on the home page work without any of that.`
    );
  }
  if (!res.ok) {
    throw new Error(
      res.status === 503
        ? "The build service is up but its database or queue is unavailable. Browse the prebuilt pages instead."
        : `Build request failed (${res.status}).`
    );
  }
  return res.json();
}

export type StreamEvent = {
  stage: string;
  message: string;
  progress: number | null;
  payload: Record<string, any>;
};

/**
 * Subscribe to build progress. Returns an unsubscribe function.
 *
 * EventSource reconnects on its own, which would restart a finished stream, so
 * the connection is closed explicitly on a terminal stage.
 */
export function streamBuild(
  slug: string,
  onEvent: (e: StreamEvent) => void,
  onError?: (err: string) => void
): () => void {
  const url = `${API_BASE}/api/build/${encodeURIComponent(slug)}/stream`;
  const source = new EventSource(url);

  const handle = (raw: MessageEvent) => {
    try {
      const data = JSON.parse(raw.data);
      onEvent(data);
      if (data.stage === "done" || data.stage === "failed") source.close();
    } catch {
      /* keepalive comments and malformed frames are ignored */
    }
  };

  // The server names each event after its stage, so listen per stage rather
  // than relying on the default `message` handler.
  for (const stage of [
    "connected", "outline", "retrieve", "transcripts",
    "segment", "score", "rank", "assemble", "done", "failed",
  ]) {
    source.addEventListener(stage, handle as EventListener);
  }
  source.onmessage = handle;
  source.onerror = () => {
    onError?.("Lost connection to the build stream.");
    source.close();
  };

  return () => source.close();
}
