/** Client-safe formatting helpers — kept out of pages.ts so client components
 *  don't drag `fs` into the browser bundle. */
export function formatTime(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}:${s.toString().padStart(2, "0")}`;
}
