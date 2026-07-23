"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { startBuild, streamBuild, type StreamEvent } from "@/lib/api";

/**
 * Live-build UX (C5).
 *
 * The perceived-latency story: the outline lands in ~5s and the page fills in
 * as sections rank, so a 60s build never feels like a 60s wait. Chapter titles
 * are rendered the moment stage 1 returns them, before any clip exists.
 */

const STAGE_LABELS: Record<string, string> = {
  connected: "Connecting",
  outline: "Planning the page",
  retrieve: "Searching YouTube",
  transcripts: "Reading transcripts",
  segment: "Finding the moments",
  score: "Scoring what matters",
  rank: "Choosing the best clips",
  assemble: "Writing it up",
  done: "Ready",
  failed: "Failed",
};

const STAGE_ORDER = [
  "outline", "retrieve", "transcripts", "segment", "score", "rank", "assemble",
];

export default function BuildStream({
  query,
  mode,
}: {
  query: string;
  mode?: "learn" | "entertain" | "perspectives";
}) {
  const router = useRouter();
  const [events, setEvents] = useState<StreamEvent[]>([]);
  const [progress, setProgress] = useState(0);
  const [outline, setOutline] = useState<{ title?: string; sections?: string[] }>({});
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);
  const started = useRef(false);

  useEffect(() => {
    // React 18 StrictMode double-invokes effects in dev; without this guard the
    // build would be enqueued twice.
    if (started.current) return;
    started.current = true;

    let unsubscribe: (() => void) | undefined;

    (async () => {
      try {
        const res = await startBuild(query, mode);
        if (res.cached && res.page) {
          router.replace(
            `${res.page.mode === "entertain" ? "/e/" : "/q/"}${res.slug}`
          );
          return;
        }

        unsubscribe = streamBuild(
          res.slug,
          (e) => {
            setEvents((prev) => [...prev, e]);
            if (typeof e.progress === "number") setProgress(e.progress);
            if (e.stage === "outline" && e.payload?.title) {
              setOutline({ title: e.payload.title, sections: e.payload.sections });
            }
            if (e.stage === "done") {
              setDone(true);
              const target = e.payload?.mode === "entertain" ? "/e/" : "/q/";
              setTimeout(() => router.replace(`${target}${res.slug}`), 600);
            }
            if (e.stage === "failed") setError(e.message || "Build failed.");
          },
          (err) => setError(err)
        );
      } catch (err) {
        setError(err instanceof Error ? err.message : "Something went wrong.");
      }
    })();

    return () => unsubscribe?.();
  }, [query, mode, router]);

  const currentStage = events.length ? events[events.length - 1].stage : "connected";

  if (error) {
    return (
      <div className="mx-auto max-w-lg py-20 text-center">
        <p className="text-sm uppercase tracking-[0.2em] text-amber-400">
          Could not build
        </p>
        <p className="mt-4 text-white/70">{error}</p>
        <button
          onClick={() => router.push("/")}
          className="mt-8 rounded-full bg-white/10 px-5 py-2.5 text-sm hover:bg-white/20"
        >
          Back to all pages
        </button>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-2xl py-16">
      <p className="text-xs uppercase tracking-[0.25em] text-accent">Building</p>
      <h1 className="mt-3 text-3xl font-semibold">{outline.title || query}</h1>

      <div
        className="mt-8 h-1 w-full overflow-hidden rounded-full bg-white/10"
        role="progressbar"
        aria-valuenow={Math.round(progress * 100)}
        aria-valuemin={0}
        aria-valuemax={100}
      >
        <div
          className="h-full rounded-full bg-accent transition-all duration-500"
          style={{ width: `${Math.max(progress * 100, 3)}%` }}
        />
      </div>

      <p className="mt-3 text-sm text-white/50">
        {done ? "Ready — taking you there." : STAGE_LABELS[currentStage] || currentStage}
      </p>

      {/* The outline lands first, so the page has shape long before clips exist. */}
      {outline.sections && outline.sections.length > 0 && (
        <div className="mt-10">
          <p className="text-xs uppercase tracking-[0.2em] text-white/35">
            Planned chapters
          </p>
          <ol className="mt-3 space-y-1.5">
            {outline.sections.map((s, i) => (
              <li key={s} className="text-[15px] text-white/70">
                <span className="mr-2 text-white/30">{i + 1}.</span>
                {s}
              </li>
            ))}
          </ol>
        </div>
      )}

      <div className="mt-10 space-y-1">
        {STAGE_ORDER.map((stage) => {
          const reached = events.some((e) => e.stage === stage);
          const active = currentStage === stage && !done;
          return (
            <div
              key={stage}
              className={`flex items-center gap-2.5 text-sm transition ${
                reached ? "text-white/70" : "text-white/25"
              }`}
            >
              <span
                className={`h-1.5 w-1.5 rounded-full ${
                  active ? "animate-pulse bg-accent" : reached ? "bg-white/50" : "bg-white/15"
                }`}
              />
              {STAGE_LABELS[stage]}
            </div>
          );
        })}
      </div>
    </div>
  );
}
