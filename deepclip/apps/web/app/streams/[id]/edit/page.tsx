"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { API_BASE } from "@/lib/api";
import { getAnonId } from "@/lib/anon";

type Clip = { position: number; video_id: string; note?: string; video_title?: string; channel?: string };

export default function EditStreamPage({ params }: { params: { id: string } }) {
  const router = useRouter();
  const id = params.id;
  const [stream, setStream] = useState<any>(null);
  const [owner, setOwner] = useState<boolean | null>(null);

  const load = () => {
    fetch(`${API_BASE}/api/streams/${id}?viewer=${encodeURIComponent(getAnonId())}`)
      .then((r) => (r.ok ? r.json() : null) as Promise<any>)
      .then((d) => { setStream(d); setOwner(!!d?.is_owner); })
      .catch(() => setOwner(false));
  };
  useEffect(load, [id]);

  const reorder = async (order: number[]) => {
    await fetch(`${API_BASE}/api/streams/${id}/reorder`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ anon_id: getAnonId(), order }),
    });
    load();
  };
  const move = (from: number, dir: -1 | 1) => {
    const clips: Clip[] = stream.clips;
    const to = from + dir;
    if (to < 0 || to >= clips.length) return;
    const order = clips.map((c) => c.position);
    [order[from], order[to]] = [order[to], order[from]];
    reorder(order);
  };
  const remove = async (position: number) => {
    await fetch(`${API_BASE}/api/streams/${id}/clips/${position}?anon_id=${encodeURIComponent(getAnonId())}`, { method: "DELETE" });
    load();
  };
  const del = async () => {
    await fetch(`${API_BASE}/api/streams/${id}?anon_id=${encodeURIComponent(getAnonId())}`, { method: "DELETE" });
    router.push("/streams");
  };

  if (owner === null) return <main className="p-16 text-center text-white/40">Loading…</main>;
  if (!owner) return (
    <main className="mx-auto max-w-lg p-16 text-center">
      <p className="text-white/60">This isn&apos;t your stream to edit.</p>
      <Link href={`/stream/${id}`} className="mt-4 inline-block text-accent hover:underline">View it →</Link>
    </main>
  );

  return (
    <main className="mx-auto min-h-[100dvh] max-w-2xl px-6 py-12">
      <Link href={`/stream/${id}`} className="text-sm text-white/45 hover:text-white">← view stream</Link>
      <div className="mt-6 flex items-center justify-between">
        <h1 className="text-3xl font-semibold">{stream.title}</h1>
        <button onClick={del} className="rounded-full border border-rose-400/30 px-3 py-1.5 text-xs text-rose-300 hover:bg-rose-400/10">
          Delete stream
        </button>
      </div>

      <ol className="mt-8 space-y-2">
        {(stream.clips || []).map((c: Clip, i: number) => (
          <li key={`${c.video_id}-${c.position}`} className="flex items-center gap-3 rounded-xl border border-edge bg-surface p-3">
            <span className="w-6 text-center text-xs text-white/30">{i + 1}</span>
            <div className="min-w-0 flex-1">
              <p className="truncate text-sm text-white/80">{c.note || c.video_title || c.video_id}</p>
              {c.channel && <p className="truncate text-xs text-white/40">{c.channel}</p>}
            </div>
            <button onClick={() => move(i, -1)} disabled={i === 0} className="text-white/40 hover:text-white disabled:opacity-25" aria-label="Move up">↑</button>
            <button onClick={() => move(i, 1)} disabled={i === stream.clips.length - 1} className="text-white/40 hover:text-white disabled:opacity-25" aria-label="Move down">↓</button>
            <button onClick={() => remove(c.position)} className="text-rose-300/60 hover:text-rose-300" aria-label="Remove clip">✕</button>
          </li>
        ))}
        {stream.clips?.length === 0 && <li className="text-sm text-white/40">No clips. Add some from any page.</li>}
      </ol>
    </main>
  );
}
