import Link from "next/link";
import ImportBox from "@/components/ImportBox";

export const metadata = {
  title: "Teach me more like this — Deep Clip Search",
  description:
    "Paste a clip you loved. Get the whole picture, in real timestamped moments.",
};

export default function ImportPage() {
  return (
    <main className="mx-auto min-h-[100dvh] max-w-xl px-6 py-16">
      <Link href="/" className="text-sm text-white/45 hover:text-white">
        ← back
      </Link>

      <header className="mb-8 mt-10">
        <p className="text-xs font-medium uppercase tracking-[0.25em] text-accent">
          Reel import
        </p>
        <h1 className="mt-4 text-4xl font-semibold leading-tight">
          Loved a clip? Go deeper.
        </h1>
        <p className="mt-4 text-[17px] leading-relaxed text-white/60">
          Paste it. We work out what it&apos;s actually about, then build a page
          of real moments that takes it further — instead of showing you four
          more of the same thing.
        </p>
      </header>

      <ImportBox />

      <section className="mt-14 space-y-4">
        <h2 className="text-xs font-medium uppercase tracking-[0.2em] text-white/40">
          How it works
        </h2>
        {[
          ["We read the clip", "Transcript for YouTube; the caption you paste for Instagram and TikTok."],
          ["We work out the intent", "Topic and depth if it teaches something. Subject and vibe if it doesn't."],
          ["We build the next step", "Real clips, timestamped, from more than one source — going deeper, not sideways."],
        ].map(([title, body], i) => (
          <div key={title} className="flex gap-3">
            <span className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-white/10 text-xs text-white/60">
              {i + 1}
            </span>
            <div>
              <p className="text-[15px] font-medium text-white/90">{title}</p>
              <p className="text-sm text-white/50">{body}</p>
            </div>
          </div>
        ))}
      </section>
    </main>
  );
}
