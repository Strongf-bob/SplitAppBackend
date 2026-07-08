import type { Metadata, Viewport } from "next";
import { Montserrat } from "next/font/google";

import "./globals.css";

const montserrat = Montserrat({
  subsets: ["latin", "cyrillic"],
  weight: ["400", "500", "600", "700", "800", "900"],
  variable: "--font-montserrat",
  display: "swap"
});

export const metadata: Metadata = {
  title: "SplitApp",
  description: "PWA-клиент SplitApp для событий, чеков, долгов и Сплитика.",
  manifest: "/manifest.webmanifest",
  appleWebApp: {
    capable: true,
    statusBarStyle: "black-translucent",
    title: "SplitApp"
  },
  icons: {
    icon: [
      { url: "/assets/icon-192.png", sizes: "192x192", type: "image/png" },
      { url: "/assets/icon-512.png", sizes: "512x512", type: "image/png" },
      { url: "/assets/icon.svg", type: "image/svg+xml" }
    ],
    apple: "/assets/apple-touch-icon.png"
  }
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
  themeColor: "#1f3d8f"
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="ru">
      <body className={`${montserrat.variable} ${montserrat.className}`}>{children}</body>
    </html>
  );
}
