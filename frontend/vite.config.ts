import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Why no dev proxy: the FastAPI backend has CORS open for any origin in
// dev, so the frontend talks to http://localhost:8000 directly via the
// VITE_BACKEND_URL env var. Keeps dev and prod identical.
export default defineConfig({
  plugins: [react()],
  server: { port: 5173 },
});
