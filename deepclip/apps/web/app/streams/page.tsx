"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { API_BASE } from "@/lib/api";
import { getAnonId } from "@/lib/anon";

type StreamRow = { id: string; title: string; stance: string; clip_count: number };

export default function StreamsPage() {
  const [streams, setStreams] = useState<StreamRow[] | null>(null);
  const [title, setTitle] = useState("");
  const [stance, setStance] = useState("");
  const [busy, setBusy] = useState(false);

  const load = () => {
    const anon = getAnonId();
    fetch(`${API_BASE}/api/streams?anon_id=${encodeURIComponent(anon)}`)
      .then((r) => (r.ok ? r.json() : { streams: [] }))
      .then((d) => setStreams(d.streams || []))
      .catch(() => setStreams([]));
  };
  useEffect(load, []);

  const create = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!title.trim()) return;
    setBusy(true);
    try {
      await fetch(`${API_BASE}/api/streams`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ anon_id: getAnonId(), title: title.trim(), stance: stance.trim() || null }),
      });
      setTitle(""); setStance(""); load();
    } finally {
      setBusy(false);
    }
  };

  return (
    <main className="mx-auto min-h-[100dvh] max-w-3xl px-6 py-16">
      <Link href="/" className="text-sm text-white/45 hover:text-white">← all pages</Link>
      <h1 className="mt-8 text-4xl font-semibold">Your perspectives</h1>
      <p className="mt-3 max-w-xl text-white/60">
        Build a stream of real clips that makes your case, then share it. Add clips
        from any page with “Add to stream”.
      </p>

      <form onSubmit={create} className="mt-8 space-y-3 rounded-xl border border-edge bg-surface p-5">
        <input
          value={title} onChange={(e) => setTitle(e.target.value)}
          placeholder="Title — e.g. Why I support this"
          className="w-full rounded-lg border border-edge bg-black/40 px-3 py-2.5 text-white placeholder:text-white/30 focus:border-white/30 focus:outline-none"
        />
        <textarea
          value={stance} onChange={(e) => setStance(e.target.value)} rows={2}
          placeholder="Your stance (optional) — one or two sentences on your view"
          className="w-full resize-none rounded-lg border border-edge bg-black/40 px-3 py-2.5 text-sm text-white placeholder:text-white/30 focus:border-white/30 focus:outline-none"
        />
        <button type="submit" disabled={!title.trim() || busy}
          className="rounded-full bg-accent px-5 py-2 text-sm font-medium text-white hover:opacity-90 disabled:opacity-40">
          {busy ? "Creating…" : "Create stream"}
        </button>
      </form>

      <section className="mt-8 space-y-3">
        {streams === null && <p className="text-white/40">Loading…</p>}
        {streams?.length === 0 && <p className="text-sm text-white/50">No streams yet.</p>}
        {(streams || []).map((s) => (
          <Link key={s.id} href={`/stream/${s.id}`}
            className="block rounded-xl border border-edge bg-surface p-5 transition hover:border-white/25">
            <h3 className="text-lg font-medium text-white">{s.title}</h3>
            {s.stance && <p className="mt-1 line-clamp-1 text-sm text-white/55">{s.stance}</p>}
            <p className="mt-2 text-xs text-white/35">{s.clip_count} clips · tap to view & share</p>
          </Link>
        ))}
      </section>
    </main>
  );
}
