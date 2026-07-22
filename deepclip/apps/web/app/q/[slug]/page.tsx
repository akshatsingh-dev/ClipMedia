import { notFound } from "next/navigation";
import Link from "next/link";
import ChapterSection from "@/components/ChapterSection";
import UnverifiedBanner from "@/components/UnverifiedBanner";
import {
  PageCompleteSentinel,
  PageViewTracker,
  SatisfactionTap,
} from "@/components/PageAnalytics";
import { getPage, slugsForMode } from "@/lib/pages";

export function generateStaticParams() {
  return slugsForMode("learn").map((slug) => ({ slug }));
}

export default function LearnPage({ params }: { params: { slug: string } }) {
  const page = getPage(params.slug);
  if (!page || page.mode !== "learn" || !page.chapters) notFound();

  const totalClips = page.chapters.reduce((n, c) => n + c.clips.length, 0);

  return (
    <main className="mx-auto max-w-3xl px-6 pb-24 pt-10">
      <PageViewTracker slug={page.slug} mode="learn" />
      <Link href="/" className="text-sm text-white/45 hover:text-white">
        ← all pages
      </Link>

      <header className="mt-8">
        <span className="text-xs font-medium uppercase tracking-[0.25em] text-sky-300">
          Learn
        </span>
        <h1 className="mt-3 text-4xl font-semibold leading-tight">{page.title}</h1>
        <p className="mt-3 max-w-xl text-[17px] leading-relaxed text-white/60">
          {page.subtitle}
        </p>
        <p className="mt-4 text-xs text-white/35">
          {page.chapters.length} chapters · {totalClips} clips · ends at the bottom
        </p>
      </header>

      {!page.timestamps_verified && <UnverifiedBanner note={page.source_note} />}

      {/* Chapter jump list — a Deep Page is a document, so give it a contents. */}
      <nav className="mt-8 flex flex-wrap gap-2">
        {page.chapters.map((c, i) => (
          <a
            key={c.title}
            href={`#ch-${i + 1}`}
            className="rounded-full border border-edge px-3 py-1.5 text-xs text-white/60 transition hover:border-white/30 hover:text-white"
          >
            {i + 1}. {c.title}
          </a>
        ))}
      </nav>

      {page.chapters.map((chapter, i) => (
        <ChapterSection key={chapter.title} chapter={chapter} index={i} slug={page.slug} />
      ))}

      <SatisfactionTap slug={page.slug} mode="learn" />

      <section className="border-t border-edge pt-12 text-center">
        <p className="text-sm uppercase tracking-[0.2em] text-sky-300">end of page</p>
        <h2 className="mt-3 text-2xl font-semibold">That&apos;s the whole picture.</h2>
        <p className="mx-auto mt-3 max-w-md text-sm text-white/55">
          {page.chapters.length} chapters, {totalClips} clips, no filler. The page
          ends — completion is the goal, not session time.
        </p>
        {/* Fires page_complete only when the reader actually reaches here. */}
        <PageCompleteSentinel slug={page.slug} mode="learn" />
        <Link
          href="/"
          className="mt-6 inline-block rounded-full bg-white/10 px-5 py-2.5 text-sm hover:bg-white/20"
        >
          Back to all pages
        </Link>
      </section>
    </main>
  );
}
