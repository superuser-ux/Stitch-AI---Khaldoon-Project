import type { Metadata } from "next";
import localFont from "next/font/local";
import "./globals.css";
import { Providers } from "./providers";

// lunaris fonts — vendored local assets only, so builds stay deterministic and offline-safe.
const geist = localFont({
  src: "./fonts/Geist-Variable.woff2",
  variable: "--font-geist",
  weight: "100 900",
  display: "swap",
});
const mono = localFont({
  src: "./fonts/GeistMono-Variable.woff2",
  variable: "--font-jbmono",
  weight: "100 900",
  display: "swap",
});
const amiri = localFont({
  src: [
    { path: "./fonts/amiri-arabic-400-normal.woff2", weight: "400", style: "normal" },
    { path: "./fonts/amiri-arabic-700-normal.woff2", weight: "700", style: "normal" },
  ],
  variable: "--font-amiri",
  display: "swap",
});
const cairo = localFont({
  src: [
    { path: "./fonts/cairo-arabic-500-normal.woff2", weight: "500", style: "normal" },
    { path: "./fonts/cairo-arabic-600-normal.woff2", weight: "600", style: "normal" },
    { path: "./fonts/cairo-arabic-700-normal.woff2", weight: "700", style: "normal" },
  ],
  variable: "--font-cairo",
  display: "swap",
});
const plexAr = localFont({
  src: [
    { path: "./fonts/ibm-plex-sans-arabic-arabic-400-normal.woff2", weight: "400", style: "normal" },
    { path: "./fonts/ibm-plex-sans-arabic-arabic-500-normal.woff2", weight: "500", style: "normal" },
    { path: "./fonts/ibm-plex-sans-arabic-arabic-600-normal.woff2", weight: "600", style: "normal" },
  ],
  variable: "--font-plex-ar",
  display: "swap",
});
const fontVars = `${geist.variable} ${mono.variable} ${amiri.variable} ${cairo.variable} ${plexAr.variable}`;

// UI chrome is English-only / LTR (interim). CONTENT (Arabic) is rendered with dir="auto"
// per-element so hooks/justifications stay correctly RTL inside the English shell.
export const metadata: Metadata = {
  title: "Tanaghom — Content Review",
  description: "Two-stage content review & approval",
};

// Apply the saved theme before paint (no flash). lunaris = light/dark only; dark is default.
const themeBoot = `(function(){try{var t=localStorage.getItem('tanaghom-theme')||'dark';document.documentElement.classList.toggle('dark',t!=='light');}catch(_){document.documentElement.classList.add('dark');}})();`;

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" dir="ltr" className={fontVars} suppressHydrationWarning>
      <head><script dangerouslySetInnerHTML={{ __html: themeBoot }} /></head>
      <body><Providers>{children}</Providers></body>
    </html>
  );
}
