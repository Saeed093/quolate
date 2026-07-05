import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        border: "hsl(220 13% 91%)",
        input: "hsl(214 14% 89%)",
        ring: "hsl(234 89% 74%)",
        background: "hsl(0 0% 100%)",
        foreground: "hsl(224 28% 16%)",
        muted: "hsl(220 20% 97%)",
        "muted-foreground": "hsl(215 16% 47%)",
        primary: "hsl(234 89% 64%)",
        "primary-foreground": "hsl(0 0% 100%)",
        secondary: "hsl(220 20% 97%)",
        "secondary-foreground": "hsl(224 28% 16%)",
        accent: "hsl(234 89% 97%)",
        "accent-foreground": "hsl(234 89% 44%)",
        destructive: "hsl(0 84% 60%)",
        "destructive-foreground": "hsl(0 0% 100%)",
        popover: "hsl(0 0% 100%)",
        "popover-foreground": "hsl(224 28% 16%)",
        card: "hsl(0 0% 100%)",
        "card-foreground": "hsl(224 28% 16%)",
        ok: "hsl(152 69% 40%)",
        verify: "hsl(38 92% 50%)",
        gap: "hsl(0 72% 51%)",
        chat: {
          user: "hsl(234 89% 64%)",
          "user-foreground": "hsl(0 0% 100%)",
          assistant: "hsl(220 20% 97%)",
          "assistant-foreground": "hsl(224 28% 16%)",
        },
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
        glow: "0 0 12px 2px hsl(234 89% 64% / 0.25)",
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
