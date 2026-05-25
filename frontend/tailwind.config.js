import typography from "@tailwindcss/typography";

/** @type {import('tailwindcss').Config} */
export default {
  // "class" strategy: dark mode is toggled by adding/removing the `dark`
  // class on <html> — done in App.tsx via document.documentElement.classList.
  darkMode: "class",
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: { extend: {} },
  plugins: [typography],
};
