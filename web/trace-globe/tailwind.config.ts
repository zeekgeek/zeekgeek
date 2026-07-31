import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./app/**/*.{js,ts,jsx,tsx,mdx}",
    "./components/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        surface: {
          DEFAULT: "#0a0f18",
          raised: "#111827",
          overlay: "rgba(10, 15, 24, 0.85)",
        },
        accent: {
          cyan: "#22d3ee",
          green: "#4ade80",
          amber: "#fbbf24",
          red: "#f87171",
          violet: "#a78bfa",
        },
      },
      fontFamily: {
        sans: ["var(--font-geist-sans)", "system-ui", "sans-serif"],
        mono: ["var(--font-geist-mono)", "monospace"],
      },
      boxShadow: {
        glow: "0 0 24px rgba(34, 211, 238, 0.35)",
      },
    },
  },
  plugins: [],
};

export default config;
