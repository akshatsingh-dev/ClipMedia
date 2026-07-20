import Link from "next/link";
import { getIndex } from "@/lib/pages";

export default function Home() {
  const pages = getIndex();

  return (
    <main className="mx-auto min-h-[100dvh] max-w-3xl px-6 py-16">
      <header className="mb-14">
        <p className="text-xs font-medium uppercase tracking-[0.25em] text-accent">
          Deep Clip Search
        </p>
        <h1 className="mt-4 text-4xl font-semibold leading-tight sm:text-5xl">
          Scroll with purpose.
        </h1>
        <p className="mt-4 max-w-xl text-[17px] leading-relaxed text-white/60">
          Real video moments, jumped to the exact timestamp, sequenced into
          something worth finishing. No generated footage. No infinite feed.
        </p>
      </header>

      <section className="space-y-3">
        <h2 className="mb-4 text-xs font-medium uppercase tracking-[0.2em] text-white/40">
          Built pages
        </h2>
        {pages.length === 0 && (
          <p className="rounded-xl border border-edge bg-surface p-5 text-sm text-white/60">
            No fixtures found. Run{" "}
            <code className="rounded bg-black/50 px-1.5 py-0.5 text-white/80">
              python3 -m eval.build_fixtures
            </code>{" "}
            from the <code className="text-white/80">deepclip/</code> directory.
          </p>
        )}
        {pages.map((p) => (
          <Link
            key={p.slug}
            href={p.mode === "learn" ? `/q/${p.slug}` : `/e/${p.slug}`}
            className="group block rounded-xl border border-edge bg-surface p-5 transition hover:border-white/25"
          >
            <div className="flex items-start justify-between gap-4">
              <div className="min-w-0">
                <span
                  className={`inline-block rounded-full px-2 py-0.5 text-[10px] font-medium uppercase tracking-wider ${
                    p.mode === "learn"
                      ? "bg-sky-500/15 text-sky-300"
                      : "bg-accent/15 text-accent"
                  }`}
                >
                  {p.mode}
                </span>
                <h3 className="mt-2 text-lg font-medium text-white group-hover:text-accent">
                  {p.title}
                </h3>
                <p className="mt-1 text-sm text-white/55">{p.subtitle}</p>
              </div>
              <span className="shrink-0 text-xs text-white/35">
                {p.clip_count} clips
              </span>
            </div>
          </Link>
        ))}
      </section>

      <section className="mt-14 rounded-xl border border-edge bg-surface/50 p-5">
        <h2 className="text-xs font-medium uppercase tracking-[0.2em] text-white/40">
          What you&apos;re looking at
        </h2>
        <p className="mt-3 text-sm leading-relaxed text-white/55">
          These pages are hand-defined fixtures, not live pipeline output — no
          YouTube or Anthropic API keys are configured in this environment.
          Channel names, titles and thumbnails are <strong className="text-white/75">real</strong>,
          resolved through YouTube&apos;s public oEmbed endpoint. Clip{" "}
          <strong className="text-white/75">timestamps are not verified</strong>;
          nothing has watched these videos yet. Judge the interaction, not the
          curation.
        </p>
      </section>

      <footer className="mt-12 text-xs text-white/30">
        Every clip credits its creator and links to the original video.
      </footer>
    </main>
  );
}
