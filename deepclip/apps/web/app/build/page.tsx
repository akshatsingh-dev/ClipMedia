"use client";

import { Suspense } from "react";
import { useSearchParams } from "next/navigation";
import Link from "next/link";
import BuildStream from "@/components/BuildStream";

function BuildInner() {
  const params = useSearchParams();
  const query = params.get("q") || "";
  const mode = params.get("mode") as "learn" | "entertain" | null;

  if (!query) {
    return (
      <div className="mx-auto max-w-lg py-24 text-center">
        <p className="text-white/60">No query given.</p>
        <Link href="/" className="mt-6 inline-block text-accent hover:underline">
          Back to search
        </Link>
      </div>
    );
  }
  return <BuildStream query={query} mode={mode || undefined} />;
}

export default function BuildPage() {
  return (
    <main className="min-h-[100dvh] px-6">
      <Suspense fallback={<div className="py-24 text-center text-white/40">Loading…</div>}>
        <BuildInner />
      </Suspense>
    </main>
  );
}
