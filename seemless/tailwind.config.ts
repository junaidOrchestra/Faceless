import type { Config } from "tailwindcss";

const config: Config = {
  darkMode: "class",
  content: [
    "./app/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
    "./lib/**/*.{ts,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        // Studio editor palette, driven by CSS variables (see globals.css) so
        // the same tokens flip between the light and dark themes.
        canvas: "rgb(var(--canvas) / <alpha-value>)",
        panel: {
          DEFAULT: "rgb(var(--panel) / <alpha-value>)",
          raised: "rgb(var(--panel-raised) / <alpha-value>)",
          hover: "rgb(var(--panel-hover) / <alpha-value>)",
        },
        hairline: "rgb(var(--hairline) / <alpha-value>)",
        cream: "rgb(var(--cream) / <alpha-value>)",
        faint: "rgb(var(--faint) / <alpha-value>)",
        accent: {
          DEFAULT: "rgb(var(--accent) / <alpha-value>)",
          hover: "rgb(var(--accent-hover) / <alpha-value>)",
          foreground: "rgb(var(--accent-foreground) / <alpha-value>)",
        },
        // shadcn-style aliases used by the UI primitives.
        background: "rgb(var(--canvas) / <alpha-value>)",
        foreground: "rgb(var(--cream) / <alpha-value>)",
        border: "rgb(var(--hairline) / <alpha-value>)",
        input: "rgb(var(--hairline) / <alpha-value>)",
        ring: "rgb(var(--accent) / <alpha-value>)",
        muted: {
          DEFAULT: "rgb(var(--panel) / <alpha-value>)",
          foreground: "rgb(var(--faint) / <alpha-value>)",
        },
        destructive: {
          DEFAULT: "rgb(var(--destructive) / <alpha-value>)",
          foreground: "rgb(var(--destructive-foreground) / <alpha-value>)",
        },
      },
      fontFamily: {
        heading: ["var(--font-bricolage)", "ui-sans-serif", "system-ui"],
        sans: ["var(--font-hanken)", "ui-sans-serif", "system-ui"],
        mono: ["var(--font-mono)", "ui-monospace", "monospace"],
      },
      borderRadius: {
        xl: "0.9rem",
        "2xl": "1.25rem",
      },
      keyframes: {
        "fade-rise": {
          "0%": { opacity: "0", transform: "translateY(10px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
        "scale-in": {
          "0%": { opacity: "0", transform: "scale(0.96)" },
          "100%": { opacity: "1", transform: "scale(1)" },
        },
        // Centered variant: preserves the -50%/-50% translate so a dialog
        // positioned at left-1/2 top-1/2 stays centered while it scales in.
        "scale-in-center": {
          "0%": { opacity: "0", transform: "translate(-50%, -50%) scale(0.96)" },
          "100%": { opacity: "1", transform: "translate(-50%, -50%) scale(1)" },
        },
        "fade-in": {
          "0%": { opacity: "0" },
          "100%": { opacity: "1" },
        },
        shimmer: {
          "100%": { transform: "translateX(100%)" },
        },
        // Playful render-panel motion.
        twinkle: {
          "0%, 100%": { opacity: "0.25", transform: "scale(0.7)" },
          "50%": { opacity: "1", transform: "scale(1.1)" },
        },
        "wand-wave": {
          "0%, 100%": { transform: "rotate(-12deg) translateY(0)" },
          "50%": { transform: "rotate(10deg) translateY(-4px)" },
        },
        bob: {
          "0%, 100%": { transform: "translateY(0)" },
          "50%": { transform: "translateY(-8px)" },
        },
        "drift-across": {
          "0%": { transform: "translateX(-130%) rotate(-8deg)", opacity: "0" },
          "15%, 85%": { opacity: "1" },
          "100%": { transform: "translateX(130%) rotate(-8deg)", opacity: "0" },
        },
        // Rising steam / bubbles for the render scenes (coffee, rocket, …).
        "float-up": {
          "0%": { opacity: "0", transform: "translateY(6px) scale(0.8)" },
          "40%": { opacity: "0.85" },
          "100%": { opacity: "0", transform: "translateY(-16px) scale(1.1)" },
        },
      },
      animation: {
        "fade-rise": "fade-rise 0.45s cubic-bezier(0.16,1,0.3,1) both",
        "scale-in": "scale-in 0.2s cubic-bezier(0.16,1,0.3,1) both",
        "scale-in-center": "scale-in-center 0.2s cubic-bezier(0.16,1,0.3,1) both",
        "fade-in": "fade-in 0.25s ease-out both",
        twinkle: "twinkle 1.8s ease-in-out infinite",
        "wand-wave": "wand-wave 1.6s ease-in-out infinite",
        bob: "bob 2.4s ease-in-out infinite",
        "drift-across": "drift-across 3.6s ease-in-out infinite",
        "float-up": "float-up 2.2s ease-in-out infinite",
      },
    },
  },
  plugins: [require("tailwindcss-animate")],
};

export default config;
