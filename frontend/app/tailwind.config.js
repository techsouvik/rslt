/** @type {import('tailwindcss').Config} */
module.exports = {
  darkMode: ["class"],
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        border: "hsl(var(--border))",
        input: "hsl(var(--input))",
        ring: "hsl(var(--ring))",
        background: "hsl(var(--background))",
        foreground: "hsl(var(--foreground))",
        primary: {
          DEFAULT: "#2563EB",
          hover: "#1d4ed8",
          light: "rgba(37, 99, 235, 0.15)",
          glow: "rgba(37, 99, 235, 0.25)",
          foreground: "#ffffff",
        },
        secondary: {
          DEFAULT: "hsl(var(--secondary))",
          foreground: "hsl(var(--secondary-foreground))",
        },
        destructive: {
          DEFAULT: "hsl(var(--destructive) / <alpha-value>)",
          foreground: "hsl(var(--destructive-foreground) / <alpha-value>)",
        },
        muted: {
          DEFAULT: "hsl(var(--muted))",
          foreground: "hsl(var(--muted-foreground))",
        },
        accent: {
          DEFAULT: "hsl(var(--accent))",
          foreground: "hsl(var(--accent-foreground))",
        },
        popover: {
          DEFAULT: "hsl(var(--popover))",
          foreground: "hsl(var(--popover-foreground))",
        },
        card: {
          DEFAULT: "hsl(var(--card))",
          foreground: "hsl(var(--card-foreground))",
        },
        glass: {
          bg: "rgba(15, 17, 26, 0.55)",
          "bg-light": "rgba(15, 17, 26, 0.40)",
          "bg-heavy": "rgba(18, 20, 32, 0.80)",
          border: "rgba(255, 255, 255, 0.06)",
          "border-strong": "rgba(255, 255, 255, 0.10)",
          "inner-glow": "rgba(255, 255, 255, 0.04)",
        },
        canvas: "#08090e",
        "text-primary": "#f0f1f5",
        "text-secondary": "#8a8f9d",
        "text-tertiary": "#5a5f6d",
        success: "#10B981",
        "success-bg": "rgba(16, 185, 129, 0.10)",
        warning: "#F59E0B",
        "warning-bg": "rgba(245, 158, 11, 0.10)",
        info: "#3B82F6",
        "border-default": "rgba(255, 255, 255, 0.08)",
        "border-subtle": "rgba(255, 255, 255, 0.04)",
      },
      fontFamily: {
        inter: ['Inter', 'sans-serif'],
        mono: ['JetBrains Mono', 'monospace'],
      },
      borderRadius: {
        xl: "calc(var(--radius) + 4px)",
        lg: "var(--radius)",
        md: "calc(var(--radius) - 2px)",
        sm: "calc(var(--radius) - 4px)",
        xs: "calc(var(--radius) - 6px)",
        "2xl": "16px",
        "3xl": "24px",
        pill: "9999px",
      },
      boxShadow: {
        xs: "0 1px 2px 0 rgb(0 0 0 / 0.05)",
        glass: "0 8px 32px rgba(0, 0, 0, 0.2), 0 1px 3px rgba(0, 0, 0, 0.15)",
        float: "0 24px 80px rgba(37, 99, 235, 0.08)",
        "inner-glow": "inset 0 1px 1px rgba(255, 255, 255, 0.04)",
      },
      keyframes: {
        "accordion-down": {
          from: { height: "0" },
          to: { height: "var(--radix-accordion-content-height)" },
        },
        "accordion-up": {
          from: { height: "var(--radix-accordion-content-height)" },
          to: { height: "0" },
        },
        "caret-blink": {
          "0%,70%,100%": { opacity: "1" },
          "20%,50%": { opacity: "0" },
        },
        spin: {
          from: { transform: "rotate(0deg)" },
          to: { transform: "rotate(360deg)" },
        },
      },
      animation: {
        "accordion-down": "accordion-down 0.2s ease-out",
        "accordion-up": "accordion-up 0.2s ease-out",
        "caret-blink": "caret-blink 1.25s ease-out infinite",
        spin: "spin 1s linear infinite",
      },
    },
  },
  plugins: [require("tailwindcss-animate")],
}
