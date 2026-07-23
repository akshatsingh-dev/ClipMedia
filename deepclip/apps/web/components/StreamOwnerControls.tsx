"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { API_BASE } from "@/lib/api";
import { getAnonId } from "@/lib/anon";

/**
 * Owner-only bar on a shared stream. The share page never exposes the author id;
 * this asks the API "am I the owner?" with the viewer's anon id and only renders
 * when the answer is yes. All edits are owner-checked server-side regardless.
 */
export default function StreamOwnerControls({ streamId }: { streamId: string }) {
  const [isOwner, setIsOwner] = useState(false);

  useEffect(() => {
    fetch(`${API_BASE}/api/streams/${streamId}?viewer=${encodeURIComponent(getAnonId())}`)
      .then((r) => (r.ok ? r.json() : {}) as Promise<any>)
      .then((d) => setIsOwner(!!d.is_owner))
      .catch(() => {});
  }, [streamId]);

  if (!isOwner) return null;

  return (
    <div className="mt-4 flex items-center gap-3 rounded-xl border border-edge bg-surface/50 p-3 text-xs">
      <span className="uppercase tracking-wider text-white/40">Your stream</span>
      <Link href={`/streams/${streamId}/edit`} className="text-accent hover:underline">
        Edit clips & order →
      </Link>
    </div>
  );
}
