"use client";

import ClipPlayer from "./ClipPlayer";
import { formatTime } from "@/lib/format";
import type { Chapter } from "@/lib/types";

/**
 * Learn Mode chapter. Scrollable document, not a feed: autoplay defaults OFF
 * (C5) because reading order matters and stacked audio would wreck it.
 */
export default function ChapterSection({
  chapter,
  index,
  slug = "",
}: {
  chapter: Chapter;
  index: number;
  slug?: string;
}) {
  const channels = new Set(chapter.clips.map((c) => c.channel));

  return (
    <section id={`ch-${index + 1}`} className="scroll-mt-20 border-t border-edge py-12">
      <div className="mb-6">
        <span className="text-xs font-medium uppercase tracking-[0.2em] text-accent">
          Chapter {index + 1}
        </span>
        <h2 className="mt-2 text-2xl font-semibold text-white sm:text-3xl">
          {chapter.title}
        </h2>
        <p className="mt-3 max-w-2xl text-[15px] leading-relaxed text-white/60">
          {chapter.intro_text}
        </p>
        {/* Surfaces the >=2-distinct-channels constraint from stage 6. */}
        <p className="mt-3 text-xs text-white/35">
          {chapter.clips.length} clips · {channels.size} channel
          {channels.size === 1 ? "" : "s"}
        </p>
      </div>

      <div className="space-y-8">
        {chapter.clips.map((clip, ci) => (
          <article key={`${clip.video_id}-${clip.t_start}`}>
            <div className="aspect-video w-full">
              <ClipPlayer
                clip={clip}
                className="h-full"
                analyticsSlug={slug}
                analyticsPosition={index * 100 + ci}
              />
            </div>
            <div className="mt-3 flex flex-wrap items-start justify-between gap-x-4 gap-y-2">
              <div className="min-w-0 flex-1">
                <p className="text-[15px] font-medium leading-snug text-white/90">
                  {clip.why}
                </p>
                <p className="mt-1 truncate text-sm text-white/50">
                  {clip.video_title}
                </p>
              </div>
              <div className="shrink-0 text-right text-xs">
                <a
                  href={clip.channel_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="block font-medium text-white/80 hover:text-accent"
                >
                  {clip.channel}
                </a>
                <a
                  href={clip.credit_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="mt-0.5 block text-white/45 hover:text-white"
                >
                  {formatTime(clip.t_start)}–{formatTime(clip.t_end)} · full video ↗
                </a>
              </div>
            </div>
          </article>
        ))}
      </div>
    </section>
  );
}
