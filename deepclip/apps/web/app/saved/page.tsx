"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { API_BASE } from "@/lib/api";
import { getAnonId } from "@/lib/anon";

type Saved = { slug: string; mode: string; title: string; saved_at: string };

export default function SavedPage() {
  const [items, setItems] = useState<Saved[] | null>(null);

  useEffect(() => {
    const anon = getAnonId();
    fetch(`${API_BASE}/api/saved?anon_id=${encodeURIComponent(anon)}`)
      .then((r) => (r.ok ? r.json() : { saved: [] }))
      .then((d) => setItems(d.saved || []))
      .catch(() => setItems([]));
  }, []);

  return (
    <main className="mx-auto min-h-[100dvh] max-w-3xl px-6 py-16">
      <Link href="/" className="text-sm text-white/45 hover:text-white">
        ← all pages
      </Link>
      <h1 className="mt-8 text-4xl font-semibold">Saved</h1>
      <p className="mt-3 text-white/55">Pages you starred, on this browser.</p>

      <section className="mt-8 space-y-3">
        {items === null && <p className="text-white/40">Loading…</p>}
        {items !== null && items.length === 0 && (
          <p className="rounded-xl border border-edge bg-surface p-5 text-sm text-white/55">
            Nothing saved yet. Open a page and tap ☆ Save.
          </p>
        )}
        {(items || []).map((s) => (
          <Link
            key={s.slug}
            href={`${s.mode === "entertain" ? "/e/" : "/q/"}${encodeURIComponent(s.slug)}`}
            className="block rounded-xl border border-edge bg-surface p-5 transition hover:border-white/25"
          >
            <span
              className={`inline-block rounded-full px-2 py-0.5 text-[10px] font-medium uppercase tracking-wider ${
                s.mode === "learn" ? "bg-sky-500/15 text-sky-300" : "bg-accent/15 text-accent"
              }`}
            >
              {s.mode}
            </span>
            <h3 className="mt-2 text-lg font-medium text-white">{s.title || s.slug}</h3>
          </Link>
        ))}
      </section>
    </main>
  );
}
