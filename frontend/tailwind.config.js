/** Tailwind maps the design tokens to utility names so components never
 *  hard-code colours (02 §6 forbids magic colour values). */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  darkMode: ["class", '[data-theme="dark"]'],
  theme: {
    extend: {
      colors: {
        bg: "var(--bg)",
        surface: "var(--surface)",
        "surface-2": "var(--surface-2)",
        border: "var(--border)",
        ink: "var(--ink)",
        "ink-2": "var(--ink-2)",
        primary: "var(--primary)",
        accent: "var(--accent)",
        warn: "var(--warn)",
        danger: "var(--danger)",
        success: "var(--success)",
        "accent-text": "var(--accent-text)",
        "warn-text": "var(--warn-text)",
        "danger-text": "var(--danger-text)",
        "success-text": "var(--success-text)",
        hl: "var(--hl)",
      },
      borderRadius: {
        control: "var(--radius-control)",
        card: "var(--radius-card)",
        dialog: "var(--radius-dialog)",
      },
      boxShadow: {
        sm: "var(--shadow-sm)",
        md: "var(--shadow-md)",
        lg: "var(--shadow-lg)",
      },
      fontFamily: {
        ui: "var(--font-ui)",
        read: "var(--font-read)",
        mono: "var(--font-mono)",
      },
      transitionTimingFunction: { ease: "var(--ease)" },
    },
  },
  plugins: [],
};
