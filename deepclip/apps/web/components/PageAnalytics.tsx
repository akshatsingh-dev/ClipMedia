"use client";

import { useEffect, useRef } from "react";
import { track } from "@/lib/analytics";

/**
 * Fires `page_view` on mount and `page_complete` when the end of the page
 * scrolls into view. Drop-in for any scrollable page; the Entertain feed emits
 * its own `end_card` event instead, since "reached the end-card" is the
 * anti-infinite-scroll signal that matters there.
 *
 * The end sentinel is a zero-height div the parent places after the last
 * section. Using intersection rather than scroll position means it fires only
 * when the reader actually reaches the bottom, not when they fling past it.
 */
export function usePageView(slug: string, mode: string) {
  const fired = useRef(false);
  useEffect(() => {
    if (fired.current) return;
    fired.current = true;
    track("page_view", { slug, mode });
  }, [slug, mode]);
}

/** Renderable page_view, so a server component can drop it in without becoming
 *  a client component itself. */
export function PageViewTracker({ slug, mode }: { slug: string; mode: string }) {
  usePageView(slug, mode);
  return null;
}

export function PageCompleteSentinel({
  slug,
  mode,
}: {
  slug: string;
  mode: string;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const fired = useRef(false);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const io = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting && !fired.current) {
          fired.current = true;
          track("page_complete", { slug, mode });
        }
      },
      { threshold: 1 }
    );
    io.observe(el);
    return () => io.disconnect();
  }, [slug, mode]);

  return <div ref={ref} aria-hidden className="h-px w-full" />;
}

/**
 * The one-tap "got what I came for" control (master doc D4). Two buttons, no
 * scale — a binary satisfied/not is what people actually answer, and it maps
 * cleanly to a rate.
 */
export function SatisfactionTap({ slug, mode }: { slug: string; mode: string }) {
  const answered = useRef(false);

  const answer = (value: number) => {
    if (answered.current) return;
    answered.current = true;
    track("satisfaction", { slug, mode, value });
  };

  return (
    <div className="mt-8 rounded-xl border border-edge bg-surface/50 p-5 text-center">
      <p className="text-sm text-white/70">Did you get what you came for?</p>
      <div className="mt-3 flex justify-center gap-3">
        <button
          onClick={() => answer(1)}
          className="rounded-full bg-white/10 px-5 py-2 text-sm text-white/80 transition hover:bg-accent hover:text-white"
        >
          Yes
        </button>
        <button
          onClick={() => answer(0)}
          className="rounded-full border border-edge px-5 py-2 text-sm text-white/60 transition hover:text-white"
        >
          Not really
        </button>
      </div>
    </div>
  );
}
