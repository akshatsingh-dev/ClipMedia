import fs from "fs";
import path from "path";
import type { IndexEntry, Page } from "./types";
import { API_BASE } from "./api";

/**
 * Page loading: real pages from the API (Postgres) first, then disk fixtures.
 *
 * Built pages live in the database and are served by the FastAPI gateway; the
 * two hand-made fixtures live on disk so the product is still browsable with no
 * backend at all. A page route tries the API, then falls back to a fixture, so
 * both a freshly-built page and the offline demo resolve through one path.
 */

const FIXTURE_DIR = path.join(process.cwd(), "public", "fixtures");
const API_TIMEOUT_MS = 3000;

function readFixtureIndex(): IndexEntry[] {
  const file = path.join(FIXTURE_DIR, "index.json");
  if (!fs.existsSync(file)) return [];
  return JSON.parse(fs.readFileSync(file, "utf8"));
}

function readFixturePage(slug: string): Page | null {
  if (!/^[a-z0-9-]+$/.test(slug)) return null; // fixtures are hyphenated slugs
  const file = path.join(FIXTURE_DIR, `${slug}.json`);
  if (!fs.existsSync(file)) return null;
  return JSON.parse(fs.readFileSync(file, "utf8"));
}

async function apiFetch(pathname: string): Promise<any | null> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), API_TIMEOUT_MS);
  try {
    const res = await fetch(`${API_BASE}${pathname}`, {
      signal: controller.signal,
      cache: "no-store",
    });
    return res.ok ? await res.json() : null;
  } catch {
    return null; // API down: fall back to fixtures
  } finally {
    clearTimeout(timer);
  }
}

/** Home-page listing: DB pages merged with fixtures (DB wins on slug clash). */
export async function getIndex(): Promise<IndexEntry[]> {
  const fixtures = readFixtureIndex();
  const api = await apiFetch("/api/pages");
  if (!api?.pages) return fixtures;

  const dbEntries: IndexEntry[] = api.pages.map((p: any) => ({
    slug: p.slug,
    title: p.title || p.slug,
    subtitle: "",
    mode: p.mode,
    query: p.slug,
    clip_count: 0,
  }));
  const seen = new Set(dbEntries.map((e) => e.slug));
  return [...dbEntries, ...fixtures.filter((f) => !seen.has(f.slug))];
}

/** One page. Tries the API (built pages), then a disk fixture. */
export async function getPage(slug: string): Promise<Page | null> {
  const decoded = decodeURIComponent(slug);
  const api = await apiFetch(`/api/pages/${encodeURIComponent(decoded)}`);
  if (api?.page) {
    return {
      ...api.page,
      slug: decoded,
      mode: api.mode,
      timestamps_verified: true, // real built page; not the unverified fixtures
      source_note: "",
    };
  }
  return readFixturePage(slug);
}

/** Fixture slugs only — used to prebuild static params. DB pages render on-demand. */
export function slugsForMode(mode: "learn" | "entertain"): string[] {
  return readFixtureIndex()
    .filter((e) => e.mode === mode)
    .map((e) => e.slug);
}

export function allSlugs(): string[] {
  return readFixtureIndex().map((e) => e.slug);
}
