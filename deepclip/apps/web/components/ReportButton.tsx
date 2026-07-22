"use client";

import { useState } from "react";
import { track } from "@/lib/analytics";

/**
 * Per-clip report control (master doc D6: a report button day one).
 *
 * On a product whose promise is "real footage, curated" the failure that most
 * damages trust is a wrong or misleading clip on contested history. There has to
 * be a way for a viewer to flag it from the first day, and it must be low
 * friction — a reason picker, not a form.
 *
 * A report writes a `report` event (kind already exists server-side) with the
 * reason and clip in `meta`. Reports surface in the same event stream the
 * metrics read from, so they are reviewable without extra plumbing.
 */

const REASONS = [
  ["wrong", "Wrong or misleading"],
  ["mismatch", "Doesn't match the topic"],
  ["broken", "Clip won't play"],
  ["offensive", "Offensive content"],
] as const;

export default function ReportButton({
  slug,
  mode,
  videoId,
  position,
}: {
  slug: string;
  mode: string;
  videoId: string;
  position?: number;
}) {
  const [open, setOpen] = useState(false);
  const [done, setDone] = useState(false);

  const report = (reason: string) => {
    track("report", {
      slug,
      mode,
      video_id: videoId,
      position,
      meta: { reason },
    });
    setDone(true);
    setOpen(false);
  };

  if (done) {
    return (
      <span className="text-xs text-white/40" role="status">
        Thanks — flagged for review.
      </span>
    );
  }

  return (
    <div className="relative inline-block">
      <button
        onClick={() => setOpen((v) => !v)}
        className="text-xs text-white/35 transition hover:text-white/70"
        aria-haspopup="menu"
        aria-expanded={open}
      >
        Report
      </button>

      {open && (
        <div
          role="menu"
          className="absolute right-0 z-20 mt-1 w-48 overflow-hidden rounded-lg border border-edge bg-surface shadow-lg"
        >
          {REASONS.map(([key, label]) => (
            <button
              key={key}
              role="menuitem"
              onClick={() => report(key)}
              className="block w-full px-3 py-2 text-left text-xs text-white/70 transition hover:bg-white/10 hover:text-white"
            >
              {label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
