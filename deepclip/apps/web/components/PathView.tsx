"use client";

import Link from "next/link";
import ChapterSection from "./ChapterSection";
import FeedSection from "./FeedSection";

/**
 * Renders an imported path with its seed clip shown as provenance.
 *
 * Showing what was pasted matters: the promise is "you liked this, here is more
 * of it", and the page is unconvincing if it does not acknowledge the seed.
 */
export default function PathView({ data }: { data: any }) {
  const { page, seed_analysis: seed } = data;
  const isEntertain = page?.mode === "entertain" || seed?.mode === "entertain";
  const topic = seed?.topic || "this";

  return (
    <>
      <header className="mt-8">
        <span className="text-xs font-medium uppercase tracking-[0.25em] text-accent">
          From your clip
        </span>
        <h1 className="mt-3 text-4xl font-semibold leading-tight">
          {page?.title || topic}
        </h1>
        <p className="mt-3 max-w-xl text-[15px] leading-relaxed text-white/60">
          {isEntertain
            ? "More of what made that clip good — ranked, not shuffled."
            : `You watched one clip about ${topic}. Here is the whole picture.`}
        </p>
      </header>

      <section className="mt-6 rounded-xl border border-edge bg-surface/50 p-4">
        <p className="text-xs uppercase tracking-[0.2em] text-white/35">Seed</p>
        <a
          href={data.seed_url}
          target="_blank"
          rel="noopener noreferrer"
          className="mt-1.5 block truncate text-sm text-white/70 hover:text-accent"
        >
          {data.seed_url}
        </a>
        {/* Instagram embeds render as official oEmbed markup only, unmodified. */}
        {seed?.embed_html && (
          <div
            className="mt-3 overflow-hidden rounded-lg"
            dangerouslySetInnerHTML={{ __html: seed.embed_html }}
          />
        )}
        {seed?.needs_confirmation && (
          <p className="mt-2 text-xs text-amber-400/80">
            Topic inferred from caption text only — check it matches what you meant.
          </p>
        )}
      </section>

      {isEntertain && page?.groups ? (
        <div className="mt-8">
          <FeedSection groups={page.groups} title={page.title || topic} />
        </div>
      ) : (
        <>
          {(page?.chapters || []).map((chapter: any, i: number) => (
            <ChapterSection key={chapter.title} chapter={chapter} index={i} />
          ))}
          <section className="border-t border-edge pt-12 text-center">
            <p className="text-sm uppercase tracking-[0.2em] text-accent">
              end of path
            </p>
            <h2 className="mt-3 text-2xl font-semibold">
              That&apos;s the full picture.
            </h2>
            <Link
              href="/"
              className="mt-6 inline-block rounded-full bg-white/10 px-5 py-2.5 text-sm hover:bg-white/20"
            >
              Build another
            </Link>
          </section>
        </>
      )}
    </>
  );
}
