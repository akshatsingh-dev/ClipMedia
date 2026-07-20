import Link from "next/link";
import { notFound } from "next/navigation";
import PathView from "@/components/PathView";
import { API_BASE } from "@/lib/api";

/**
 * Imported-path renderer (A4.3).
 *
 * Reel-import writes a row to `learning_paths` and the worker returns its id;
 * this is where that lands. Server-rendered so the OG share card resolves — the
 * share loop is the point of the feature, and a client-only page would give
 * crawlers nothing.
 */

type PathData = {
  id: string;
  seed_url: string;
  seed_analysis: Record<string, any>;
  page: any;
};

async function getPath(id: string): Promise<PathData | null> {
  try {
    const res = await fetch(`${API_BASE}/api/paths/${encodeURIComponent(id)}`, {
      cache: "no-store",
    });
    return res.ok ? await res.json() : null;
  } catch {
    return null;
  }
}

export async function generateMetadata({ params }: { params: { id: string } }) {
  const data = await getPath(params.id);
  const topic = data?.seed_analysis?.topic || "this";
  const description =
    data?.seed_analysis?.mode === "entertain"
      ? `From 1 clip → the best of ${topic}.`
      : `From 1 reel → the full picture of ${topic}.`;
  const title = data?.page?.title || "Your path";
  return { title, description, openGraph: { title, description } };
}

export default async function PathPage({ params }: { params: { id: string } }) {
  const data = await getPath(params.id);
  if (!data) notFound();
  return (
    <main className="mx-auto max-w-3xl px-6 pb-24 pt-10">
      <Link href="/" className="text-sm text-white/45 hover:text-white">
        ← all pages
      </Link>
      <PathView data={data} />
    </main>
  );
}
