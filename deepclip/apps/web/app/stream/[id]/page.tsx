import Link from "next/link";
import { notFound } from "next/navigation";
import ClipPlayer from "@/components/ClipPlayer";
import { API_BASE } from "@/lib/api";

/**
 * Public perspective-stream view (research/perspective-streams.md).
 *
 * Server-rendered so the OG share card resolves — sharing is the point. The page
 * is labeled explicitly as ONE PERSON'S perspective, never objective truth, which
 * is the ethical guardrail the whole feature rests on.
 */

async function getStream(id: string) {
  try {
    const res = await fetch(`${API_BASE}/api/streams/${encodeURIComponent(id)}`, {
      cache: "no-store",
    });
    return res.ok ? await res.json() : null;
  } catch {
    return null;
  }
}

export async function generateMetadata({ params }: { params: { id: string } }) {
  const s = await getStream(params.id);
  const title = s?.title || "A perspective";
  const description = `A perspective in ${s?.clips?.length ?? 0} real clips.`;
  return { title, description, openGraph: { title, description } };
}

export default async function StreamPage({ params }: { params: { id: string } }) {
  const stream = await getStream(params.id);
  if (!stream) notFound();

  return (
    <main className="mx-auto max-w-3xl px-6 pb-24 pt-10">
      <Link href="/" className="text-sm text-white/45 hover:text-white">
        ← Deep Clip Search
      </Link>

      <header className="mt-8">
        {/* The non-negotiable label: this is a viewpoint, not the truth. */}
        <span className="text-xs font-medium uppercase tracking-[0.25em] text-accent">
          A personal perspective
        </span>
        <h1 className="mt-3 text-4xl font-semibold leading-tight">{stream.title}</h1>
        {stream.stance && (
          <p className="mt-3 max-w-xl text-[17px] leading-relaxed text-white/70">
            {stream.stance}
          </p>
        )}
        <p className="mt-4 text-xs text-white/35">
          {stream.clips.length} real clips · one person&apos;s view, backed by
          primary footage · every clip credits its source
        </p>
      </header>

      <div className="mt-8 rounded-xl border border-amber-500/20 bg-amber-500/5 p-3 text-xs text-white/55">
        This is a viewpoint someone assembled, not a neutral summary. Want the
        other sides?{" "}
        <Link href={`/build?q=${encodeURIComponent(stream.title)}`} className="text-accent hover:underline">
          See multiple perspectives →
        </Link>
      </div>

      <div className="mt-8 space-y-8">
        {stream.clips.map((clip: any, i: number) => (
          <article key={`${clip.video_id}-${clip.t_start}-${i}`}>
            <div className="aspect-video w-full">
              <ClipPlayer clip={clip} className="h-full" />
            </div>
            <div className="mt-3 flex flex-wrap items-start justify-between gap-x-4 gap-y-2">
              <div className="min-w-0 flex-1">
                {clip.note && (
                  <p className="text-[15px] font-medium leading-snug text-white/90">
                    {clip.note}
                  </p>
                )}
                {clip.video_title && (
                  <p className="mt-1 truncate text-sm text-white/50">{clip.video_title}</p>
                )}
              </div>
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

      <section className="mt-14 border-t border-edge pt-10 text-center">
        <p className="text-sm text-white/55">Make your own perspective stream.</p>
        <Link
          href="/"
          className="mt-4 inline-block rounded-full bg-accent px-5 py-2.5 text-sm font-medium text-white hover:opacity-90"
        >
          Start on Deep Clip Search
        </Link>
      </section>
    </main>
  );
}
