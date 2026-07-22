"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import ClipPlayer from "./ClipPlayer";
import type { Clip, Group } from "@/lib/types";
import { track } from "@/lib/analytics";
import ReportButton from "./ReportButton";

/**
 * Entertain Mode feed.
 *
 * Interaction pattern is the short-form convention (full-viewport snap scroll,
 * one clip per pane, autoplay on intersection, right-rail actions) implemented
 * from scratch — see DECISIONS D5. No third-party code or assets.
 *
 * The one deliberate divergence: this feed ENDS. There is an end-card and no
 * loop. That rule is inviolable per master doc A4.4 / D6 — the brand dies the
 * moment this feels like a slot machine.
 */

type FeedClip = Clip & { groupLabel: string };

export default function FeedSection({
  groups,
  title,
  slug = "",
}: {
  groups: Group[];
  title: string;
  slug?: string;
}) {
  // Interleave across groupings so the feed varies subject, matching the
  // server-side ranking behaviour in rank_entertain.interleave().
  const clips: FeedClip[] = [];
  const maxLen = Math.max(0, ...groups.map((g) => g.clips.length));
  for (let i = 0; i < maxLen; i++) {
    for (const g of groups) {
      if (g.clips[i]) clips.push({ ...g.clips[i], groupLabel: g.label });
    }
  }

  const containerRef = useRef<HTMLDivElement>(null);
  const [active, setActive] = useState(0);
  const [autoAdvance, setAutoAdvance] = useState(true);

  // page_view once on mount.
  const viewFired = useRef(false);
  useEffect(() => {
    if (viewFired.current) return;
    viewFired.current = true;
    track("page_view", { slug, mode: "entertain" });
  }, [slug]);

  // end_card when the reader reaches the end pane. In a feed this — not
  // "scrolled a lot" — is the completion signal, because the whole promise is
  // that the feed ends.
  const endFired = useRef(false);
  useEffect(() => {
    if (active >= clips.length && !endFired.current) {
      endFired.current = true;
      track("end_card", { slug, mode: "entertain", position: clips.length });
    }
  }, [active, clips.length, slug]);

  const goTo = useCallback((idx: number) => {
    const el = containerRef.current?.children[idx] as HTMLElement | undefined;
    el?.scrollIntoView({ behavior: "smooth" });
  }, []);

  // Track which pane is centred, for the progress rail and auto-advance.
  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    const io = new IntersectionObserver(
      (entries) => {
        for (const e of entries) {
          if (e.isIntersecting && e.intersectionRatio > 0.6) {
            const idx = Number((e.target as HTMLElement).dataset.idx);
            if (!Number.isNaN(idx)) setActive(idx);
          }
        }
      },
      { root: container, threshold: [0.6] }
    );
    Array.from(container.children).forEach((c) => io.observe(c));
    return () => io.disconnect();
  }, [clips.length]);

  // Keyboard nav — desktop testing needs this; arrows are the obvious mapping.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "ArrowDown" || e.key === "j") goTo(Math.min(active + 1, clips.length));
      if (e.key === "ArrowUp" || e.key === "k") goTo(Math.max(active - 1, 0));
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [active, clips.length, goTo]);

  const handleEnded = useCallback(
    (idx: number) => {
      if (!autoAdvance) return;
      // Do not advance past the last clip. The end-card is the destination.
      if (idx < clips.length) goTo(idx + 1);
    },
    [autoAdvance, clips.length, goTo]
  );

  return (
    <div className="relative">
      {/* progress rail */}
      <div className="fixed right-2 top-1/2 z-40 hidden -translate-y-1/2 flex-col gap-1.5 md:flex">
        {clips.map((_, i) => (
          <button
            key={i}
            onClick={() => goTo(i)}
            aria-label={`Go to clip ${i + 1}`}
            className={`h-5 w-1 rounded-full transition-all ${
              i === active ? "bg-accent" : "bg-white/25 hover:bg-white/50"
            }`}
          />
        ))}
      </div>

      <div className="fixed left-4 top-4 z-40 flex items-center gap-3">
        <Link
          href="/"
          className="rounded-full bg-black/60 px-3 py-1.5 text-sm text-white/80 backdrop-blur hover:text-white"
        >
          ← back
        </Link>
        <button
          onClick={() => setAutoAdvance((v) => !v)}
          className="rounded-full bg-black/60 px-3 py-1.5 text-sm text-white/80 backdrop-blur hover:text-white"
        >
          auto-advance {autoAdvance ? "on" : "off"}
        </button>
      </div>

      <div
        ref={containerRef}
        className="h-[100dvh] snap-y snap-mandatory overflow-y-scroll scroll-smooth"
      >
        {clips.map((clip, i) => (
          <FeedPane
            key={`${clip.video_id}-${clip.t_start}`}
            clip={clip}
            idx={i}
            total={clips.length}
            onEnded={() => handleEnded(i)}
            slug={slug}
          />
        ))}
        <EndCard idx={clips.length} count={clips.length} title={title} />
      </div>
    </div>
  );
}

function FeedPane({
  clip,
  idx,
  total,
  onEnded,
  slug,
}: {
  clip: FeedClip;
  idx: number;
  total: number;
  onEnded: () => void;
  slug: string;
}) {
  return (
    <section
      data-idx={idx}
      className="relative flex h-[100dvh] snap-start snap-always items-center justify-center bg-ink"
    >
      {/* Portrait stage, the short-form frame. */}
      <div className="relative h-full w-full max-w-[min(100vw,calc(100dvh*9/16))]">
        <ClipPlayer
          clip={clip}
          autoplay
          onEnded={onEnded}
          rounded={false}
          className="h-full"
          analyticsSlug={slug}
          analyticsPosition={idx}
        />

        {/* bottom gradient + metadata */}
        <div className="pointer-events-none absolute inset-x-0 bottom-0 bg-gradient-to-t from-black via-black/70 to-transparent p-4 pb-8">
          <div className="pointer-events-auto">
            <span className="mb-2 inline-block rounded-full bg-white/15 px-2.5 py-1 text-[11px] uppercase tracking-wide text-white/80 backdrop-blur">
              {clip.groupLabel}
            </span>
            <p className="mb-1 text-[15px] font-medium leading-snug text-white">
              {clip.why}
            </p>
            <a
              href={clip.channel_url}
              target="_blank"
              rel="noopener noreferrer"
              className="text-sm font-semibold text-white/90 hover:text-accent"
            >
              @{clip.channel}
            </a>
            <p className="mt-0.5 line-clamp-1 text-xs text-white/55">
              {clip.video_title}
            </p>
            <div className="mt-2 flex items-center gap-3">
              <a
                href={clip.credit_url}
                target="_blank"
                rel="noopener noreferrer"
                className="text-xs text-white/60 underline decoration-white/30 hover:text-white"
              >
                watch full video →
              </a>
              <ReportButton
                slug={slug}
                mode="entertain"
                videoId={clip.video_id}
                position={idx}
              />
            </div>
          </div>
        </div>

        <div className="absolute right-3 top-4 rounded-full bg-black/50 px-2.5 py-1 text-xs text-white/70 backdrop-blur">
          {idx + 1} / {total}
        </div>
      </div>
    </section>
  );
}

function EndCard({ idx, count, title }: { idx: number; count: number; title: string }) {
  return (
    <section
      data-idx={idx}
      className="flex h-[100dvh] snap-start snap-always flex-col items-center justify-center bg-ink px-6 text-center"
    >
      <p className="text-sm uppercase tracking-[0.2em] text-accent">that&apos;s the feed</p>
      <h2 className="mt-4 max-w-lg text-3xl font-semibold text-white">
        You&apos;ve seen the best {count}.
      </h2>
      <p className="mt-3 max-w-md text-white/60">
        No more to scroll — that&apos;s the point. {title} ends here, on purpose.
      </p>
      <div className="mt-8 flex flex-wrap justify-center gap-3">
        <Link
          href="/"
          className="rounded-full bg-accent px-5 py-2.5 text-sm font-medium text-white hover:opacity-90"
        >
          Try a different vibe
        </Link>
        <button
          onClick={() => window.scrollTo({ top: 0 })}
          className="rounded-full border border-edge px-5 py-2.5 text-sm text-white/70 hover:text-white"
        >
          Watch again
        </button>
      </div>
    </section>
  );
}
