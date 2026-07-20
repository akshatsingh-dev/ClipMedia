import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Deep Clip Search — scroll with purpose",
  description:
    "Real video moments, jumped to the exact timestamp, sequenced on purpose.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="bg-ink font-sans text-white antialiased">{children}</body>
    </html>
  );
}
