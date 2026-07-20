/**
 * Honesty banner (DECISIONS D3).
 *
 * Fixture timestamps were never verified against the actual footage. Without
 * this notice a viewer would reasonably assume the clip boundaries were curated,
 * which is exactly the impression this product must not create falsely.
 */
export default function UnverifiedBanner({ note }: { note: string }) {
  return (
    <div className="mt-8 rounded-xl border border-amber-500/25 bg-amber-500/5 p-4">
      <p className="text-xs font-medium uppercase tracking-wider text-amber-400/90">
        Demo data
      </p>
      <p className="mt-1.5 text-sm leading-relaxed text-white/60">{note}</p>
    </div>
  );
}
