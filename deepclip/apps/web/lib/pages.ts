import fs from "fs";
import path from "path";
import type { IndexEntry, Page } from "./types";

/**
 * Fixture-backed page loading (DECISIONS D4).
 *
 * The UI reads fixture JSON from disk so the product is viewable without
 * Postgres, Redis, or API keys. When the real pipeline is wired, this module is
 * the single place to swap for a fetch against the FastAPI gateway.
 */

const FIXTURE_DIR = path.join(process.cwd(), "public", "fixtures");

export function getIndex(): IndexEntry[] {
  const file = path.join(FIXTURE_DIR, "index.json");
  if (!fs.existsSync(file)) return [];
  return JSON.parse(fs.readFileSync(file, "utf8"));
}

export function getPage(slug: string): Page | null {
  // Guard against traversal — slug comes straight from the URL.
  if (!/^[a-z0-9-]+$/.test(slug)) return null;
  const file = path.join(FIXTURE_DIR, `${slug}.json`);
  if (!fs.existsSync(file)) return null;
  return JSON.parse(fs.readFileSync(file, "utf8"));
}

export function allSlugs(): string[] {
  return getIndex().map((e) => e.slug);
}

export function slugsForMode(mode: "learn" | "entertain"): string[] {
  return getIndex()
    .filter((e) => e.mode === mode)
    .map((e) => e.slug);
}
