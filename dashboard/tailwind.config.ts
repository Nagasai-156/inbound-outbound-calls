import type { Config } from "tailwindcss";

export default {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        bg: "#0d1117",
        card: "#161b22",
        line: "#30363d",
        muted: "#8b949e",
        accent: "#2f81f7",
        ok: "#3fb950",
        bad: "#f85149",
      },
    },
  },
  plugins: [],
} satisfies Config;
