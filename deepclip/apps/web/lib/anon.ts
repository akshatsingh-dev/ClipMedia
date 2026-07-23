/**
 * The anonymous, per-browser id — shared by analytics and saved-pages so both
 * key off the same identity. A random UUID in localStorage; no login, no PII.
 * An account can later adopt this id without migrating any data.
 */

const ANON_KEY = "dcs_anon_id";

export function uuid(): string {
  try {
    if (typeof crypto !== "undefined" && crypto.randomUUID) return crypto.randomUUID();
  } catch {
    /* fall through */
  }
  return `x-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

export function getAnonId(): string {
  if (typeof window === "undefined") return "ssr";
  try {
    let id = localStorage.getItem(ANON_KEY);
    if (!id) {
      id = uuid();
      localStorage.setItem(ANON_KEY, id);
    }
    return id;
  } catch {
    return "no-storage";
  }
}
