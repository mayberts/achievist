/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // Clean modern dark palette (Trophies Hunter-inspired)
        ink: {
          950: "#0a0d14",
          900: "#0e121b",
          850: "#121826",
          800: "#161d2e",
          700: "#1e2740",
          600: "#2a3654",
        },
        line: "#232c42",
        accent: {
          DEFAULT: "#5b8cff",
          soft: "#3a5bd0",
        },
        good: "#3ecf8e",
        warn: "#f0b429",
        muted: "#7c8aa5",
        faint: "#4d5a75",
      },
      fontFamily: {
        sans: ["Inter", "system-ui", "Segoe UI", "sans-serif"],
      },
      borderRadius: {
        card: "12px",
      },
    },
  },
  plugins: [],
};
