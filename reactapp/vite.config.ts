import { defineConfig } from "vite";
import react from "@vitejs/plugin-react-swc";
import path from "path";

const backend = "http://127.0.0.1:5000";

export default defineConfig({
  server: {
    port: 8080,
    proxy: {
      "/api": backend,
      "/video_feed": backend,
      "/socket.io": { target: backend, ws: true },
    },
  },
  plugins: [react()],
  resolve: {
    alias: { "@": path.resolve(__dirname, "./src") },
  },
});
