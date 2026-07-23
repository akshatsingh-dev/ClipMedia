"use client";

import { useEffect, useState } from "react";
import { API_BASE } from "@/lib/api";
import { getAnonId } from "@/lib/anon";
import type { Clip } from "@/lib/types";

/**
 * "Add to stream" — puts a clip into one of the user's perspective streams
 * (research/perspective-streams.md). Loads the user's streams on open; can also
 * create a new one inline. Keyed by anon_id, no login.
 */
export default function AddToStream({ clip }: { clip: Clip }) {
  const [open, setOpen] = useState(false);
  const [streams, setStreams] = useState<{ id: string; title: string }[]>([]);
  const [added, setAdded] = useState(false);
  const [newTitle, setNewTitle] = useState("");

  useEffect(() => {
    if (!open) return;
    fetch(`${API_BASE}/api/streams?anon_id=${encodeURIComponent(getAnonId())}`)
      .then((r) => (r.ok ? r.json() : { streams: [] }))
      .then((d) => setStreams(d.streams || []))
      .catch(() => setStreams([]));
  }, [open]);

  const clipPayload = () => ({
    video_id: clip.video_id,
    t_start: clip.t_start,
    t_end: clip.t_end,
    note: clip.why || "",
    channel: clip.channel,
    video_title: clip.video_title,
  });

  const addTo = async (streamId: string) => {
    await fetch(`${API_BASE}/api/streams/${streamId}/clips`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(clipPayload()),
    });
    setAdded(true);
    setOpen(false);
  };

  const createAndAdd = async () => {
    if (!newTitle.trim()) return;
    const res = await fetch(`${API_BASE}/api/streams`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ anon_id: getAnonId(), title: newTitle.trim(), clips: [clipPayload()] }),
    });
    if (res.ok) { setAdded(true); setOpen(false); }
  };

  if (added) return <span className="text-xs text-accent">✓ Added to stream</span>;

  return (
    <div className="relative inline-block">
      <button onClick={() => setOpen((v) => !v)}
        className="text-xs text-white/35 transition hover:text-accent">
        + Add to stream
      </button>
      {open && (
        <div className="absolute right-0 z-20 mt-1 w-60 rounded-lg border border-edge bg-surface p-2 shadow-lg">
          {streams.map((s) => (
            <button key={s.id} onClick={() => addTo(s.id)}
              className="block w-full truncate rounded px-2 py-1.5 text-left text-xs text-white/70 hover:bg-white/10 hover:text-white">
              {s.title}
            </button>
          ))}
          <div className="mt-1 flex gap-1 border-t border-edge pt-2">
            <input value={newTitle} onChange={(e) => setNewTitle(e.target.value)}
              placeholder="New stream…"
              className="min-w-0 flex-1 rounded bg-black/40 px-2 py-1 text-xs text-white placeholder:text-white/30 focus:outline-none" />
            <button onClick={createAndAdd} className="rounded bg-accent px-2 py-1 text-xs text-white">Add</button>
          </div>
        </div>
      )}
    </div>
  );
}
