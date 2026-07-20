"use client";

import { Suspense } from "react";
import Link from "next/link";

/**
 * Shown when the import was queued rather than completed inline. The worker
 * writes the path row when it finishes; this page just sets expectations
 * honestly rather than spinning forever.
 */
function Pending() {
  return (
    <div className="mx-auto max-w-lg py-24 text-center">
      <p className="text-xs uppercase tracking-[0.25em] text-accent">Working on it</p>
      <h1 className="mt-4 text-3xl font-semibold">Reading your clip.</h1>
      <p className="mt-4 text-white/60">
        Building a page takes up to a minute. It&apos;ll appear under your paths
        when it&apos;s ready.
      </p>
      <Link
        href="/"
        className="mt-8 inline-block rounded-full bg-white/10 px-5 py-2.5 text-sm hover:bg-white/20"
      >
        Back to all pages
      </Link>
    </div>
  );
}

export default function PendingPage() {
  return (
    <main className="min-h-[100dvh] px-6">
      <Suspense fallback={<div className="py-24 text-center text-white/40">Loading…</div>}>
        <Pending />
      </Suspense>
    </main>
  );
}
