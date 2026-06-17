import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./pages/**/*.{js,ts,jsx,tsx,mdx}",
    "./components/**/*.{js,ts,jsx,tsx,mdx}",
    "./app/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        background: "var(--background)",
        foreground: "var(--foreground)",
        // Фирменная палитра reHome (как на rehome.one): тёплый оранжевый
        // primary, чаркол-текст, мятный вторичный акцент, тёплый фон.
        brand: {
          DEFAULT: "var(--brand)",
          hover: "var(--brand-hover)",
          soft: "var(--brand-soft)",
        },
        ink: "var(--ink)",
        mint: {
          DEFAULT: "var(--mint)",
          soft: "var(--mint-soft)",
        },
        sand: "var(--sand)",
      },
    },
  },
  plugins: [],
};
export default config;
