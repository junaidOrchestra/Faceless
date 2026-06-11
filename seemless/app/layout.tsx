import type { Metadata } from "next";
import { Bricolage_Grotesque, Hanken_Grotesk, JetBrains_Mono } from "next/font/google";
import "./globals.css";
import { FeedbackWidget } from "@/components/feedback/feedback-dialog";

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

export const metadata: Metadata = {
  title: "Brollio — narration to video",
  description:
    "Turn a narration audio file into a narrated faceless video by reviewing and picking a visual for each spoken beat.",
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
        <FeedbackWidget />
      </body>
    </html>
  );
}
