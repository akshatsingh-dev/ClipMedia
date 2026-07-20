/**
 * Share-card copy (C3 reel-import): "From 1 reel → the full picture of {topic}."
 *
 * Mirrors share_card_text() in services/worker/pipeline/reel_import.py. Kept in
 * both places deliberately: the worker needs it when persisting a path, the
 * frontend needs it for OG tags without a round trip.
 */
export function shareCardText(topic: string, mode: "learn" | "entertain"): string {
  const subject = topic?.trim() || "this";
  return mode === "entertain"
    ? `From 1 clip → the best of ${subject}.`
    : `From 1 reel → the full picture of ${subject}.`;
}

export function pageShareText(title: string, clipCount: number, mode: string): string {
  return mode === "entertain"
    ? `${clipCount} clips, best first, then it ends. No algorithm.`
    : `${title} in ${clipCount} real clips — every one timestamped to the moment.`;
}
