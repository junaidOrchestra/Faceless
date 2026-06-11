import type { Metadata } from "next";
import { Bricolage_Grotesque, Hanken_Grotesk, JetBrains_Mono } from "next/font/google";
import "./globals.css";

const bricolage = Bricolage_Grotesque({
  subsets: ["latin"],
  variable: "--font-bricolage",
  display: "swap",
  weight: ["400", "500", "600", "700", "800"],
});

const hanken = Hanken_Grotesk({
  subsets: ["latin"],
  variable: "--font-hanken",
  display: "swap",
});

const mono = JetBrains_Mono({
  subsets: ["latin"],
  variable: "--font-mono",
  display: "swap",
});

const TITLE = "Brollio — turn your voice into faceless videos";
const DESCRIPTION =
  "Brollio turns a narration voiceover into a captioned, faceless video — beat by beat. Upload audio, pick a stock clip for each spoken moment, and render. No camera, no timeline.";

export const metadata: Metadata = {
  metadataBase: new URL("https://brollio.app"),
  title: TITLE,
  description: DESCRIPTION,
  keywords: [
    "faceless video",
    "b-roll",
    "voiceover to video",
    "AI video editor",
    "stock footage",
    "auto captions",
    "shorts",
    "reels",
  ],
  openGraph: {
    title: TITLE,
    description: DESCRIPTION,
    type: "website",
    siteName: "Brollio",
  },
  twitter: {
    card: "summary_large_image",
    title: TITLE,
    description: DESCRIPTION,
  },
};

// Applies the saved (or default dark) theme before paint to avoid a flash.
const themeScript = `(function(){try{var t=localStorage.getItem('theme');var dark=t?t==='dark':true;var r=document.documentElement;r.classList.toggle('dark',dark);r.classList.toggle('light',!dark);}catch(e){document.documentElement.classList.add('dark');}})();`;

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: themeScript }} />
      </head>
      <body
        suppressHydrationWarning
        className={`${bricolage.variable} ${hanken.variable} ${mono.variable}`}
      >
        {children}
      </body>
    </html>
  );
}
