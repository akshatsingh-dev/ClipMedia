"use client";

import { useState } from "react";
import ClipPlayer from "./ClipPlayer";

/**
 * Multi-perspective view (research/perspective-streams.md).
 *
 * Shows a contested subject through labeled lenses. The design guardrails are
 * visual, not just data: a neutral header states this is not the platform's
 * view, every lens is reachable (tabs show all of them), and each lens is
 * labeled by what it argues. You cannot land in one lens without seeing the
 * others exist.
 */

const LENS_META: Record<string, { label: string; color: string }> = {
  supportive: { label: "The case for", color: "text-emerald-300 border-emerald-400/40" },
  critical: { label: "The case against", color: "text-rose-300 border-rose-400/40" },
  neutral: { label: "Neutral / fact-check", color: "text-sky-300 border-sky-400/40" },
};

export default function PerspectivesView({ page }: { page: any }) {
  const lenses = page.lenses || [];
  const [active, setActive] = useState(lenses[0]?.label);
  const current = lenses.find((l: any) => l.label === active) || lenses[0];

  return (
    <>
      <header className="mt-8">
        <span className="text-xs font-medium uppercase tracking-[0.25em] text-accent">
          Multiple perspectives
        </span>
        <h1 className="mt-3 text-4xl font-semibold leading-tight">{page.title}</h1>
        <p className="mt-3 rounded-xl border border-amber-500/20 bg-amber-500/5 p-3 text-sm text-white/60">
          {page.notice ||
            "This subject is shown through several lenses, each built from real clips. No lens is the platform's view."}
        </p>
      </header>

      {/* Lens tabs — all sides always visible. */}
      <div className="mt-6 flex flex-wrap gap-2">
        {lenses.map((l: any) => {
          const meta = LENS_META[l.label] || { label: l.label, color: "text-white/70 border-edge" };
          const on = l.label === active;
          return (
            <button
              key={l.label}
              onClick={() => setActive(l.label)}
              className={`rounded-full border px-4 py-1.5 text-sm transition ${
                on ? `${meta.color} bg-white/5` : "border-edge text-white/50 hover:text-white/80"
              }`}
            >
              {meta.label}
            </button>
          );
        })}
      </div>

      {current && (
        <section className="mt-6">
          {current.stance && (
            <p className="mb-6 text-[17px] leading-relaxed text-white/75">{current.stance}</p>
          )}
          <div className="space-y-8">
            {current.clips.map((clip: any, i: number) => (
              <article key={`${clip.video_id}-${clip.t_start}-${i}`}>
                <div className="aspect-video w-full">
                  <ClipPlayer clip={clip} className="h-full" />
                </div>
                <div className="mt-3 flex flex-wrap items-start justify-between gap-x-4 gap-y-2">
                  <p className="min-w-0 flex-1 text-[15px] font-medium leading-snug text-white/90">
                    {clip.why}
                  </p>
                  <a
                    href={clip.credit_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="shrink-0 text-xs text-white/45 hover:text-white"
                  >
                    {clip.channel || "source"} · full video ↗
                  </a>
                </div>
              </article>
            ))}
          </div>
        </section>
      )}
    </>
  );
}
