"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

/**
 * Query entry. Mode is a hint, not a requirement — stage 1 classifies it — so
 * the default is "decide for me" rather than forcing a choice the user should
 * not have to think about.
 */
export default function SearchBox() {
  const router = useRouter();
  const [query, setQuery] = useState("");
  const [mode, setMode] = useState<"auto" | "learn" | "entertain">("auto");

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    const q = query.trim();
    if (!q) return;
    const params = new URLSearchParams({ q });
    if (mode !== "auto") params.set("mode", mode);
    router.push(`/build?${params.toString()}`);
  };

  return (
    <form onSubmit={submit} className="w-full">
      <div className="flex flex-col gap-2 sm:flex-row">
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Teach me about the Salt March — or, best Messi solo goals"
          aria-label="What do you want to see?"
          className="flex-1 rounded-xl border border-edge bg-surface px-4 py-3 text-[15px] text-white placeholder:text-white/30 focus:border-white/30 focus:outline-none"
        />
        <button
          type="submit"
          disabled={!query.trim()}
          className="rounded-xl bg-accent px-6 py-3 text-[15px] font-medium text-white transition hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-40"
        >
          Build
        </button>
      </div>

      <div className="mt-3 flex gap-1.5">
        {(["auto", "learn", "entertain"] as const).map((m) => (
          <button
            key={m}
            type="button"
            onClick={() => setMode(m)}
            className={`rounded-full px-3 py-1 text-xs transition ${
              mode === m
                ? "bg-white/15 text-white"
                : "text-white/40 hover:text-white/70"
            }`}
          >
            {m === "auto" ? "decide for me" : m}
          </button>
        ))}
      </div>
    </form>
  );
}
