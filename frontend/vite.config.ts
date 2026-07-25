import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev proxy mirrors the prod Firebase Hosting rewrite (/api/** → Cloud Run),
// so the frontend code is identical in both environments.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": "http://localhost:8080",
    },
  },
});
