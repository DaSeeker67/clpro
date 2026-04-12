import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Cluely Pro — Stealth AI Meeting Copilot",
  description:
    "Screen-capture-proof AI assistant for meetings, interviews, and assessments. Invisible overlay with real-time answers.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <head>
        <link
          href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap"
          rel="stylesheet"
        />
      </head>
      <body>{children}</body>
    </html>
  );
}
