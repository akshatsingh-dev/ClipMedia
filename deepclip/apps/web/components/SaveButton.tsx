"use client";

import { useEffect, useState } from "react";
import { API_BASE } from "@/lib/api";
import { getAnonId } from "@/lib/anon";

/**
 * Save-a-page control (D3, Pro tier). Keyed by the anonymous id, so it works
 * without a login — an account can adopt the anon_id later without losing saves.
 *
 * Optimistic: the button flips immediately and reconciles with the server, so a
 * slow request never makes the UI feel unresponsive.
 */
export default function SaveButton({
  slug,
  mode,
  title,
}: {
  slug: string;
  mode: string;
  title: string;
}) {
  const [saved, setSaved] = useState(false);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    const anon = getAnonId();
    fetch(`${API_BASE}/api/saved?anon_id=${encodeURIComponent(anon)}`)
      .then((r) => (r.ok ? r.json() : { saved: [] }))
      .then((d) => {
        setSaved((d.saved || []).some((s: any) => s.slug === slug));
        setReady(true);
      })
      .catch(() => setReady(true));
  }, [slug]);

  const toggle = async () => {
    const anon = getAnonId();
    const next = !saved;
    setSaved(next); // optimistic
    try {
      if (next) {
        await fetch(`${API_BASE}/api/saved`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ anon_id: anon, slug, mode, title }),
        });
      } else {
        await fetch(
          `${API_BASE}/api/saved?anon_id=${encodeURIComponent(anon)}&slug=${encodeURIComponent(slug)}`,
          { method: "DELETE" }
        );
      }
    } catch {
      setSaved(!next); // revert on failure
    }
  };

  return (
    <button
      onClick={toggle}
      disabled={!ready}
      aria-pressed={saved}
      className={`rounded-full border px-3 py-1.5 text-xs transition ${
        saved
          ? "border-accent bg-accent/15 text-accent"
          : "border-edge text-white/60 hover:text-white"
      }`}
    >
      {saved ? "★ Saved" : "☆ Save"}
    </button>
  );
}
