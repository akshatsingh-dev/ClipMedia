import { notFound } from "next/navigation";
import FeedSection from "@/components/FeedSection";
import { getPage, slugsForMode } from "@/lib/pages";

export function generateStaticParams() {
  return slugsForMode("entertain").map((slug) => ({ slug }));
}

export default function EntertainPage({ params }: { params: { slug: string } }) {
  const page = getPage(params.slug);
  if (!page || page.mode !== "entertain" || !page.groups) notFound();

  return <FeedSection groups={page.groups} title={page.title} slug={page.slug} />;
}
