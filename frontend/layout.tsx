import type { Metadata, Viewport } from "next";
import type { ReactNode } from "react";

import Shell from "@/components/Shell";

import "./globals.css";

export const metadata: Metadata = {
  title: "Mac Fundamental Intelligence",
  description: "Fundamental macro research terminal: central banks, forecasts, surprises, scenarios and trade bias.",
};

export const viewport: Viewport = { themeColor: "#0f1c2e", width: "device-width", initialScale: 1 };

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="" />
        <link
          href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Serif:ital,wght@0,400;0,500;1,400&display=swap"
          rel="stylesheet"
        />
      </head>
      <body>
        <Shell>{children}</Shell>
      </body>
    </html>
  );
}
