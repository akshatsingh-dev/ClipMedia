"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { API_BASE } from "@/lib/api";

/**
 * Reel-import (A4.3) — the wedge.
 *
 * Paste a clip you liked, get a path that goes deeper. This is the only part of
 * the product that demonstrates in ten seconds, which is what a short-form
 * acquisition loop actually needs.
 *
 * Platform handling is a legal constraint, not a UX preference (master doc B4):
 * YouTube links can be analysed end to end, but Instagram and TikTok cannot be
 * fetched at all — so for those the user must paste the caption themselves, and
 * the UI has to explain why rather than appearing broken.
 */

type Platform = "youtube" | "instagram" | "tiktok" | "unknown";

const YT = /(?:youtube\.com\/(?:watch\?(?:.*&)?v=|shorts\/|embed\/)|youtu\.be\/)([A-Za-z0-9_-]{11})/;
const IG = /instagram\.com\/(?:reel|reels|p|tv)\/([A-Za-z0-9_-]+)/;
const TT = /tiktok\.com\/(?:@[\w.]+\/video\/(\d+)|v\/(\d+))/;

export function detectPlatform(url: string): Platform {
  if (YT.test(url)) return "youtube";
  if (IG.test(url)) return "instagram";
  if (TT.test(url)) return "tiktok";
  return "unknown";
}

const NEEDS_CAPTION: Platform[] = ["instagram", "tiktok"];

export default function ImportBox() {
  const router = useRouter();
  const [url, setUrl] = useState("");
  const [caption, setCaption] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const platform = url.trim() ? detectPlatform(url) : "unknown";
  const needsCaption = NEEDS_CAPTION.includes(platform);
  const canSubmit =
    url.trim().length > 0 &&
    platform !== "unknown" &&
    (!needsCaption || caption.trim().length > 0) &&
    !busy;

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!canSubmit) return;
    setBusy(true);
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/api/import`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url: url.trim(), caption_text: caption.trim() || undefined }),
      });
      if (!res.ok) throw new Error(`Import failed (${res.status})`);
      const data = await res.json();
      if (data.path_id) {
        router.push(`/path/${data.path_id}`);
      } else {
        // The worker returns a job id; the path appears when it finishes.
        router.push(`/import/pending?job=${encodeURIComponent(data.job_id || "")}`);
      }
    } catch {
      setError(
        `Can't reach the import service at ${API_BASE}. It needs the API, a worker, ` +
          `Postgres, Redis and both API keys running.`
      );
      setBusy(false);
    }
  };

  return (
    <form onSubmit={submit} className="w-full">
      <input
        value={url}
        onChange={(e) => setUrl(e.target.value)}
        placeholder="Paste a Short, Reel, or TikTok you liked"
        aria-label="Clip URL"
        className="w-full rounded-xl border border-edge bg-surface px-4 py-3 text-[15px] text-white placeholder:text-white/30 focus:border-white/30 focus:outline-none"
      />

      {platform !== "unknown" && (
        <p className="mt-2 text-xs text-white/40">
          Detected: <span className="text-white/70">{platform}</span>
        </p>
      )}
      {url.trim() && platform === "unknown" && (
        <p className="mt-2 text-xs text-amber-400/80">
          Not a link I recognise. YouTube, Instagram, or TikTok.
        </p>
      )}

      {needsCaption && (
        <div className="mt-3 rounded-xl border border-amber-500/25 bg-amber-500/5 p-3">
          <p className="text-xs text-white/70">
            {platform === "instagram" ? "Instagram" : "TikTok"} doesn&apos;t allow
            us to read the clip, so paste its caption and we&apos;ll work from that.
          </p>
          <textarea
            value={caption}
            onChange={(e) => setCaption(e.target.value)}
            rows={3}
            placeholder="Paste the caption here"
            aria-label="Clip caption"
            className="mt-2 w-full resize-none rounded-lg border border-edge bg-black/40 px-3 py-2 text-sm text-white placeholder:text-white/25 focus:border-white/30 focus:outline-none"
          />
        </div>
      )}

      <button
        type="submit"
        disabled={!canSubmit}
        className="mt-3 w-full rounded-xl bg-accent px-6 py-3 text-[15px] font-medium text-white transition hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-40"
      >
        {busy ? "Reading the clip…" : "Teach me more like this"}
      </button>

      {error && <p className="mt-3 text-sm text-amber-400/90">{error}</p>}

      <p className="mt-3 text-xs leading-relaxed text-white/35">
        We never download or re-host anything. Instagram and TikTok clips are
        shown through their own official embeds, and every clip credits its
        creator.
      </p>
    </form>
  );
}
