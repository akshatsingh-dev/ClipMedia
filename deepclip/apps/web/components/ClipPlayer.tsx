"use client";

import { useEffect, useRef, useState } from "react";
import type { Clip } from "@/lib/types";
import { track } from "@/lib/analytics";

/**
 * Lazy-mounted YouTube embed (C5, mandatory).
 *
 * A thumbnail façade renders until the clip scrolls into view; only then does an
 * iframe mount. Mounting 20+ iframes eagerly costs several hundred ms of main
 * thread each and will jank the feed on a phone, which is the one thing this
 * product cannot afford.
 */

type Props = {
  clip: Clip;
  /** Autoplay once in view. On in Entertain, off in Learn (C5). */
  autoplay?: boolean;
  /** Fires when the clip reaches t_end, for auto-advance. */
  onEnded?: () => void;
  className?: string;
  rounded?: boolean;
  /** Page slug and clip index, for analytics. Optional so the player still
   *  works in isolation (e.g. tests) without an analytics context. */
  analyticsSlug?: string;
  analyticsPosition?: number;
};

export default function ClipPlayer({
  clip,
  autoplay = false,
  onEnded,
  className = "",
  rounded = true,
  analyticsSlug,
  analyticsPosition,
}: Props) {
  const wrapRef = useRef<HTMLDivElement>(null);
  const [inView, setInView] = useState(false);
  const [activated, setActivated] = useState(false);

  useEffect(() => {
    const el = wrapRef.current;
    if (!el) return;
    const io = new IntersectionObserver(
      ([entry]) => setInView(entry.isIntersecting && entry.intersectionRatio > 0.5),
      { threshold: [0, 0.5, 1] }
    );
    io.observe(el);
    return () => io.disconnect();
  }, []);

  // In autoplay mode, scrolling into view is the play gesture.
  useEffect(() => {
    if (autoplay && inView) setActivated(true);
  }, [autoplay, inView]);

  // t_end is not enforced by the iframe reliably, so a timer backstops it.
  // Without this the feed silently runs past the curated moment into filler.
  useEffect(() => {
    if (!activated || !onEnded) return;
    const durationMs = Math.max((clip.t_end - clip.t_start) * 1000, 1000);
    const timer = setTimeout(onEnded, durationMs);
    return () => clearTimeout(timer);
  }, [activated, clip.t_start, clip.t_end, onEnded]);

  // clip_complete fires when a clip plays its full curated span. value = 1.0
  // here because the timer only fires on completion; partial-watch tracking
  // would need the IFrame API's time updates, a later refinement.
  useEffect(() => {
    if (!activated || !onEnded) return;
    const durationMs = Math.max((clip.t_end - clip.t_start) * 1000, 1000);
    const t = setTimeout(() => {
      track("clip_complete", {
        slug: analyticsSlug,
        video_id: clip.video_id,
        position: analyticsPosition,
        value: 1.0,
      });
    }, durationMs);
    return () => clearTimeout(t);
  }, [activated, clip, analyticsSlug, analyticsPosition, onEnded]);

  // clip_view once, when it first becomes visible.
  const viewed = useRef(false);
  useEffect(() => {
    if (inView && !viewed.current) {
      viewed.current = true;
      track("clip_view", {
        slug: analyticsSlug,
        video_id: clip.video_id,
        position: analyticsPosition,
      });
    }
  }, [inView, clip.video_id, analyticsSlug, analyticsPosition]);

  // Unmount the iframe when it leaves view in autoplay feeds — this is what
  // actually stops audio from three clips overlapping.
  const shouldRender = activated && (!autoplay || inView);

  const src =
    `https://www.youtube.com/embed/${clip.video_id}` +
    `?start=${Math.floor(clip.t_start)}&end=${Math.ceil(clip.t_end)}` +
    `&enablejsapi=1&rel=0&modestbranding=1&playsinline=1` +
    (autoplay ? "&autoplay=1&mute=1" : "&autoplay=1");

  const radius = rounded ? "rounded-xl" : "";

  return (
    <div
      ref={wrapRef}
      className={`relative w-full overflow-hidden bg-black ${radius} ${className}`}
    >
      {shouldRender ? (
        <iframe
          key={`${clip.video_id}-${clip.t_start}`}
          src={src}
          title={clip.video_title}
          className="absolute inset-0 h-full w-full"
          allow="accelerometer; autoplay; encrypted-media; gyroscope; picture-in-picture"
          allowFullScreen
        />
      ) : (
        <button
          type="button"
          onClick={() => setActivated(true)}
          className="group absolute inset-0 h-full w-full"
          aria-label={`Play ${clip.video_title}`}
        >
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src={clip.thumbnail}
            alt=""
            className="h-full w-full object-cover opacity-80 transition group-hover:opacity-100"
            loading="lazy"
          />
          <span className="absolute inset-0 flex items-center justify-center">
            <span className="flex h-16 w-16 items-center justify-center rounded-full bg-black/60 backdrop-blur transition group-hover:scale-110 group-hover:bg-accent">
              <svg viewBox="0 0 24 24" className="ml-1 h-7 w-7 fill-white">
                <path d="M8 5v14l11-7z" />
              </svg>
            </span>
          </span>
        </button>
      )}
    </div>
  );
}
