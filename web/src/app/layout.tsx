import type { Metadata, Viewport } from "next";

import "./globals.css";

export const metadata: Metadata = {
  title: "SplitApp",
  description: "PWA-клиент SplitApp для событий, чеков, долгов и Сплитика.",
  manifest: "/manifest.webmanifest",
  icons: {
    icon: "/assets/icon.svg",
    apple: "/assets/icon.svg"
  }
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
  themeColor: "#0f172a"
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="ru">
      <body>{children}</body>
    </html>
  );
}
