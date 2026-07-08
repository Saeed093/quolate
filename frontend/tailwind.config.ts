import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: "#14213D",
        "ink-deep": "#0E1830",
        paper: "#F2F4F0",
        teal: "#12A594",
        amber: "#E1A83D",
        slate: "#56606E",
        "slate-soft": "#8991A0",
        border: "#E3E2DA",
        input: "#E3E2DA",
        ring: "#12A594",
        background: "#F2F4F0",
        foreground: "#14213D",
        muted: "#E8EAE6",
        "muted-foreground": "#56606E",
        primary: "#14213D",
        "primary-foreground": "#F2F4F0",
        secondary: "#E8EAE6",
        "secondary-foreground": "#14213D",
        accent: "rgba(20, 33, 61, 0.06)",
        "accent-foreground": "#14213D",
        destructive: "hsl(0 84% 60%)",
        "destructive-foreground": "#F2F4F0",
        popover: "#FFFFFF",
        "popover-foreground": "#14213D",
        card: "#FFFFFF",
        "card-foreground": "#14213D",
        ok: "#12A594",
        verify: "#E1A83D",
        gap: "hsl(0 72% 51%)",
        chat: {
          user: "#0E1830",
          "user-foreground": "#F2F4F0",
          assistant: "#E8EAE6",
          "assistant-foreground": "#14213D",
        },
      },
      fontFamily: {
        sans: ["var(--font-inter)", "Inter", "system-ui", "sans-serif"],
        display: ["var(--font-space-grotesk)", "Space Grotesk", "system-ui", "sans-serif"],
        mono: ["var(--font-ibm-plex-mono)", "IBM Plex Mono", "ui-monospace", "monospace"],
      },
      borderRadius: {
        xl: "0.75rem",
        lg: "0.5rem",
        md: "0.375rem",
        sm: "0.25rem",
      },
      boxShadow: {
        soft: "0 1px 3px 0 rgb(0 0 0 / 0.04), 0 1px 2px -1px rgb(0 0 0 / 0.04)",
        card: "0 2px 8px -2px rgb(0 0 0 / 0.06), 0 1px 3px -1px rgb(0 0 0 / 0.04)",
        lift: "0 8px 24px -4px rgb(0 0 0 / 0.08), 0 2px 6px -2px rgb(0 0 0 / 0.04)",
        drawer: "-4px 0 24px -4px rgb(0 0 0 / 0.1)",
        glow: "0 0 12px 2px rgba(18, 165, 148, 0.2)",
      },
      keyframes: {
        "fade-in": { from: { opacity: "0" }, to: { opacity: "1" } },
        "fade-out": { from: { opacity: "1" }, to: { opacity: "0" } },
        "bounce-dot": {
          "0%, 80%, 100%": { transform: "scale(0.6)", opacity: "0.4" },
          "40%": { transform: "scale(1)", opacity: "1" },
        },
        "slide-in-right": {
          from: { transform: "translateX(100%)" },
          to: { transform: "translateX(0)" },
        },
        "slide-out-right": {
          from: { transform: "translateX(0)" },
          to: { transform: "translateX(100%)" },
        },
        "slide-in-up": {
          from: { transform: "translateY(8px)", opacity: "0" },
          to: { transform: "translateY(0)", opacity: "1" },
        },
        "fade-in-up": {
          from: { transform: "translateY(4px)", opacity: "0" },
          to: { transform: "translateY(0)", opacity: "1" },
        },
        "pulse-glow": {
          "0%, 100%": { opacity: "1", boxShadow: "0 0 4px 1px currentColor" },
          "50%": { opacity: "0.6", boxShadow: "0 0 8px 3px currentColor" },
        },
        "pulse-ring": {
          "0%": { transform: "scale(1)", opacity: "1" },
          "100%": { transform: "scale(1.8)", opacity: "0" },
        },
      },
      animation: {
        "fade-in": "fade-in 0.2s ease-out",
        "bounce-dot": "bounce-dot 1.4s ease-in-out infinite",
        "slide-in-right": "slide-in-right 0.3s cubic-bezier(0.16,1,0.3,1)",
        "slide-out-right": "slide-out-right 0.25s cubic-bezier(0.16,1,0.3,1)",
        "slide-in-up": "slide-in-up 0.3s ease-out",
        "fade-in-up": "fade-in-up 0.25s ease-out",
        "pulse-glow": "pulse-glow 2s ease-in-out infinite",
        "pulse-ring": "pulse-ring 1.5s ease-out infinite",
      },
    },
  },
  plugins: [require("tailwindcss-animate")],
};

export default config;
