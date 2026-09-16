import { defineConfig } from "vite";

export default defineConfig({
  base: process.env.VITE_PUBLIC_BASE || (process.env.VITE_APP_MODE === "demo" ? "/ai-evaluation-workbench/" : "/"),
  server: {
    host: "127.0.0.1",
    port: 5173,
    strictPort: true,
    proxy: { "/api": "http://127.0.0.1:8000" },
    hmr: { host: "127.0.0.1" },
  },
});
